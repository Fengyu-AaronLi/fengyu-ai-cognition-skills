#!/usr/bin/env python3
"""V17 red contracts for importing immutable red-stage evidence into a later loop."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_red_evidence.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class RedEvidenceFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.test_path = root / "tests" / "test_v17_contract.py"
        self.test_path.parent.mkdir(parents=True)
        self.test_path.write_text("# frozen red contract\n", encoding="utf-8")
        self.workflow = root / "workflows" / "v17.json"
        write_json(
            self.workflow,
            {
                "schema_version": "1.0",
                "workflow_id": "identity-v17-red-evidence",
                "steps": [],
            },
        )
        self.manifest = root / "evals" / "test-generation-manifest.json"
        write_json(
            self.manifest,
            {
                "schema_version": "1.0",
                "files": [
                    {
                        "generation": "v17",
                        "path": "tests/test_v17_contract.py",
                        "sha256": digest(self.test_path),
                    }
                ],
            },
        )
        self.run_dir = root / "evals" / "runs" / "red-001"
        stdout = self.run_dir / "raw" / "red.stdout.txt"
        stderr = self.run_dir / "raw" / "red.stderr.txt"
        stdout.parent.mkdir(parents=True)
        stdout.write_text("", encoding="utf-8")
        stderr.write_text(
            "Ran 2 tests in 0.010s\n\nFAILED (failures=2)\n",
            encoding="utf-8",
        )
        receipt = self.run_dir / "receipts" / "red.json"
        write_json(
            receipt,
            {
                "schema_version": "1.0",
                "run_id": "red-001",
                "candidate_id": "candidate-red-001",
                "workflow_sha256": digest(self.workflow),
                "step_id": "red",
                "kind": "command",
                "argv": [sys.executable, str(self.test_path), "-v"],
                "exit_code": 1,
                "assertion": "red",
                "assertion_passed": False,
                "stdout_path": "evals/runs/red-001/raw/red.stdout.txt",
                "stdout_sha256": digest(stdout),
                "stderr_path": "evals/runs/red-001/raw/red.stderr.txt",
                "stderr_sha256": digest(stderr),
                "recorded_at": "2026-08-06T00:00:00Z",
            },
        )
        write_json(
            self.run_dir / "run-state.json",
            {
                "schema_version": "1.0",
                "run_id": "red-001",
                "candidate_id": "candidate-red-001",
                "workflow_path": "workflows/v17.json",
                "workflow_sha256": digest(self.workflow),
                "status": "failed",
                "steps": {
                    "red": {
                        "kind": "command",
                        "status": "failed",
                        "receipt_path": "evals/runs/red-001/receipts/red.json",
                        "receipt_sha256": digest(receipt),
                    }
                },
            },
        )

    def verify(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                "--root",
                str(self.root),
                "--run-dir",
                str(self.run_dir),
                "--step-id",
                "red",
                "--test-path",
                str(self.test_path),
                "--test-manifest",
                str(self.manifest),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )


class RedEvidenceVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v17-red-evidence-")
        self.fixture = RedEvidenceFixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_accepts_hash_bound_registered_assertion_failure(self) -> None:
        result = self.fixture.verify()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(2, payload["failure_count"])

    def test_rejects_tampered_raw_output(self) -> None:
        raw = self.fixture.run_dir / "raw" / "red.stderr.txt"
        raw.write_text("forged\n", encoding="utf-8")
        result = self.fixture.verify()
        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("red_evidence_raw_hash_mismatch", result.stdout)

    def test_rejects_test_not_bound_to_manifest(self) -> None:
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        manifest["files"][0]["sha256"] = "0" * 64
        write_json(self.fixture.manifest, manifest)
        result = self.fixture.verify()
        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("red_evidence_test_manifest_mismatch", result.stdout)


if __name__ == "__main__":
    unittest.main()
