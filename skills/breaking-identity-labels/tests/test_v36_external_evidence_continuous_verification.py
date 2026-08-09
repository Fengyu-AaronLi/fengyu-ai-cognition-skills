#!/usr/bin/env python3
"""V36 contracts for continuously verified external-step evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts" / "run_evolution.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def errors(result: subprocess.CompletedProcess[str]) -> set[str]:
    value = json.loads(result.stdout) if result.stdout.strip() else {}
    return set(value.get("errors", []))


class ExternalEvidenceFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        for relative in ("scripts", "workflows", "evals/runs", "evals/external", "evidence"):
            (root / relative).mkdir(parents=True, exist_ok=True)
        (root / "scripts" / "red.py").write_text(
            "print('Ran 1 test')\nprint('FAILED (failures=1)')\nraise SystemExit(1)\n",
            encoding="utf-8",
        )
        self.evidence = root / "evidence" / "refinement.md"
        self.evidence.write_text("reviewed refinement\n", encoding="utf-8")
        self.workflow = root / "workflows" / "external.json"
        write_json(
            self.workflow,
            {
                "schema_version": "1.0",
                "workflow_id": "identity-v36-external-evidence",
                "steps": [
                    {
                        "id": "targeted_red",
                        "kind": "command",
                        "depends_on": [],
                        "argv": ["{python}", "{root}/scripts/red.py"],
                        "expected": "red",
                    },
                    {
                        "id": "refinement",
                        "kind": "external",
                        "depends_on": ["targeted_red"],
                    },
                ],
            },
        )
        self.run_dir = root / "evals" / "runs" / "v36"

    def controller(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CONTROLLER), *args, "--root", str(self.root)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def complete(self) -> None:
        started = self.controller(
            "run",
            "--workflow",
            str(self.workflow),
            "--run-dir",
            str(self.run_dir),
            "--run-id",
            "v36",
            "--candidate-id",
            "candidate-v36",
        )
        if started.returncode != 2:
            raise AssertionError(started.stdout + started.stderr)
        source = self.root / "evals" / "external" / "refinement.json"
        write_json(
            source,
            {
                "schema_version": "1.0",
                "run_id": "v36",
                "step_id": "refinement",
                "status": "completed",
                "summary": "independent refinement complete",
                "evidence": [
                    {
                        "path": "evidence/refinement.md",
                        "sha256": digest(self.evidence),
                    }
                ],
            },
        )
        accepted = self.controller(
            "complete-external",
            "--run-dir",
            str(self.run_dir),
            "--step-id",
            "refinement",
            "--receipt",
            str(source),
        )
        if accepted.returncode != 0:
            raise AssertionError(accepted.stdout + accepted.stderr)
        resumed = self.controller("resume", "--run-dir", str(self.run_dir))
        if resumed.returncode != 0:
            raise AssertionError(resumed.stdout + resumed.stderr)


class ExternalEvidenceContinuousVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v36-external-")
        self.fixture = ExternalEvidenceFixture(Path(self.temporary.name))
        self.fixture.complete()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_status_rejects_external_evidence_content_drift(self) -> None:
        self.fixture.evidence.write_text("changed after approval\n", encoding="utf-8")

        result = self.fixture.controller("status", "--run-dir", str(self.fixture.run_dir))

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("evolution_external_evidence_hash_mismatch", errors(result))

    def test_status_rejects_external_evidence_disappearance(self) -> None:
        moved = self.fixture.evidence.with_suffix(".moved")
        self.fixture.evidence.rename(moved)

        result = self.fixture.controller("status", "--run-dir", str(self.fixture.run_dir))

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("evolution_external_evidence_hash_mismatch", errors(result))

    def test_drifted_predecessor_cannot_seed_a_new_iteration(self) -> None:
        self.fixture.evidence.write_text("changed after approval\n", encoding="utf-8")
        next_run = self.fixture.root / "evals" / "runs" / "v37"

        result = self.fixture.controller(
            "next-iteration",
            "--previous-run-dir",
            str(self.fixture.run_dir),
            "--run-dir",
            str(next_run),
            "--run-id",
            "v37",
            "--candidate-id",
            "candidate-v37",
        )

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("evolution_external_evidence_hash_mismatch", errors(result))
        self.assertFalse(next_run.exists())


if __name__ == "__main__":
    unittest.main()
