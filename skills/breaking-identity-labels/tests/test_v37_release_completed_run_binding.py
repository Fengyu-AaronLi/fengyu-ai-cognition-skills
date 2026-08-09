#!/usr/bin/env python3
"""V37 contracts binding a release freeze to one verified completed run."""

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
DEMO_FILES = (
    ".case.lock",
    "analysis.json",
    "case.json",
    "demo-input.txt",
    "events.head.json",
    "events.jsonl",
    "report.md",
    "run-manifest.json",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout) if result.stdout.strip() else {}


class ReleaseRunFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        for relative in (
            "scripts",
            "schemas",
            "tests",
            "workflows",
            "evals/runs",
            "examples/real-run",
        ):
            (root / relative).mkdir(parents=True, exist_ok=True)
        files = {
            "scripts/identity_label_case.py": "print('runtime')\n",
            "scripts/run_evolution.py": "# controller governance fixture\n",
            "scripts/build_demo.py": "# demo builder governance fixture\n",
            "evals/validate.py": "# evaluator governance fixture\n",
            "scripts/worker.py": "print('OK')\n",
            "tests/test_v37_contract.py": "# frozen V37 contract\n",
        }
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        (root / "scripts" / "build_package.py").write_text(
            "import json\nprint(json.dumps({'tree_sha256': 'f' * 64}))\n",
            encoding="utf-8",
        )
        write_json(root / "schemas" / "case.schema.json", {"type": "object"})
        write_json(root / "schemas" / "release-gate.schema.json", {"type": "object"})
        for name in DEMO_FILES:
            (root / "examples" / "real-run" / name).write_text(
                f"fixture:{name}\n",
                encoding="utf-8",
            )
        self.manifest = root / "evals" / "test-generation-manifest.json"
        test_path = root / "tests" / "test_v37_contract.py"
        write_json(
            self.manifest,
            {
                "schema_version": "1.0",
                "generation_rules": [
                    {"generation": "v37", "minimum": 1, "pattern": "tests/test_v37_*.py"}
                ],
                "files": [
                    {
                        "generation": "v37",
                        "path": "tests/test_v37_contract.py",
                        "sha256": digest(test_path),
                    }
                ],
            },
        )
        self.workflow = root / "workflows" / "release.json"
        write_json(
            self.workflow,
            {
                "schema_version": "1.0",
                "workflow_id": "identity-v37-release-binding",
                "steps": [
                    {
                        "id": "green",
                        "kind": "command",
                        "depends_on": [],
                        "argv": ["{python}", "{root}/scripts/worker.py"],
                        "expected": "exit_zero",
                    }
                ],
            },
        )
        self.run_dir = root / "evals" / "runs" / "completed"
        self.release_state = root / "evals" / "release-gate.json"

    def controller(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CONTROLLER),
                *args,
                "--root",
                str(self.root),
                "--state",
                str(self.release_state),
                "--test-manifest",
                str(self.manifest),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def complete_run(self, *, candidate_id: str = "candidate-v37") -> None:
        result = self.controller(
            "run",
            "--workflow",
            str(self.workflow),
            "--run-dir",
            str(self.run_dir),
            "--run-id",
            "v37-run",
            "--candidate-id",
            candidate_id,
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)

    def freeze(self, *, candidate_id: str = "candidate-v37", bind: bool = True) -> subprocess.CompletedProcess[str]:
        args = [
            "freeze",
            "--candidate-id",
            candidate_id,
            "--workflow",
            str(self.workflow),
        ]
        if bind:
            args.extend(["--completed-run-dir", str(self.run_dir)])
        return self.controller(*args)


class ReleaseCompletedRunBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v37-release-")
        self.fixture = ReleaseRunFixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_freeze_refuses_to_create_an_unbound_release_candidate(self) -> None:
        result = self.fixture.freeze(bind=False)

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("release_completed_run_required", set(payload(result).get("errors", [])))
        self.assertFalse(self.fixture.release_state.exists())

    def test_freeze_binds_run_state_event_head_receipt_tree_and_workflow(self) -> None:
        self.fixture.complete_run()
        result = self.fixture.freeze()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

        state = json.loads(self.fixture.release_state.read_text(encoding="utf-8"))
        binding = state["completed_run"]
        run_state = json.loads(
            (self.fixture.run_dir / "run-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual("evals/runs/completed", binding["run_dir"])
        self.assertEqual("v37-run", binding["run_id"])
        self.assertEqual("candidate-v37", binding["candidate_id"])
        self.assertEqual(run_state["event_head_sha256"], binding["event_head_sha256"])
        self.assertEqual(run_state["event_count"], binding["event_count"])
        self.assertEqual(digest(self.fixture.run_dir / "run-state.json"), binding["run_state_sha256"])
        self.assertRegex(binding["receipt_tree_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual("workflows/release.json", state["workflow_path"])

    def test_freeze_rejects_candidate_or_workflow_not_matching_the_completed_run(self) -> None:
        self.fixture.complete_run(candidate_id="candidate-from-run")
        wrong_candidate = self.fixture.freeze(candidate_id="different-candidate")
        self.assertEqual(3, wrong_candidate.returncode, wrong_candidate.stdout + wrong_candidate.stderr)
        self.assertIn(
            "release_completed_run_candidate_mismatch",
            set(payload(wrong_candidate).get("errors", [])),
        )

        other_workflow = self.fixture.root / "workflows" / "other.json"
        value = json.loads(self.fixture.workflow.read_text(encoding="utf-8"))
        value["workflow_id"] = "identity-v37-other"
        write_json(other_workflow, value)
        mismatch = self.fixture.controller(
            "freeze",
            "--candidate-id",
            "candidate-from-run",
            "--workflow",
            str(other_workflow),
            "--completed-run-dir",
            str(self.fixture.run_dir),
        )
        self.assertEqual(3, mismatch.returncode, mismatch.stdout + mismatch.stderr)
        self.assertIn(
            "release_completed_run_workflow_mismatch",
            set(payload(mismatch).get("errors", [])),
        )

    def test_gate_revalidates_the_bound_run_instead_of_trusting_saved_hashes(self) -> None:
        self.fixture.complete_run()
        self.assertEqual(0, self.fixture.freeze().returncode)
        run_state_path = self.fixture.run_dir / "run-state.json"
        run_state_path.write_text(
            run_state_path.read_text(encoding="utf-8") + " ",
            encoding="utf-8",
        )

        checked = self.fixture.controller("check", "--allow-blocked")

        self.assertEqual(3, checked.returncode, checked.stdout + checked.stderr)
        self.assertIn(
            "release_completed_run_state_hash_mismatch",
            set(payload(checked).get("errors", [])),
        )

    def test_gate_rejects_removing_the_completed_run_binding(self) -> None:
        self.fixture.complete_run()
        self.assertEqual(0, self.fixture.freeze().returncode)
        state = json.loads(self.fixture.release_state.read_text(encoding="utf-8"))
        state.pop("completed_run")
        write_json(self.fixture.release_state, state)

        checked = self.fixture.controller("check", "--strict-release")

        self.assertEqual(3, checked.returncode, checked.stdout + checked.stderr)
        self.assertIn("release_completed_run_required", set(payload(checked).get("errors", [])))


if __name__ == "__main__":
    unittest.main()
