#!/usr/bin/env python3
"""V13 contracts for a real resumable evolution loop and add-only tests."""

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
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout) if result.stdout.strip() else {}


class LoopFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        for relative in ("scripts", "workflows", "evals/runs", "evals/external"):
            (root / relative).mkdir(parents=True, exist_ok=True)
        (root / "scripts" / "red.py").write_text(
            "print('Ran 1 test')\nprint('FAILED (failures=1)')\nraise SystemExit(1)\n",
            encoding="utf-8",
        )
        (root / "scripts" / "green.py").write_text("print('OK')\n", encoding="utf-8")
        self.workflow = root / "workflows" / "loop.json"
        write_json(
            self.workflow,
            {
                "schema_version": "1.0",
                "workflow_id": "identity-v13-test-loop",
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
                    {
                        "id": "targeted_green",
                        "kind": "command",
                        "depends_on": ["refinement"],
                        "argv": ["{python}", "{root}/scripts/green.py"],
                        "expected": "exit_zero",
                    },
                ],
            },
        )
        self.run_dir = root / "evals" / "runs" / "r1"

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CONTROLLER), *args, "--root", str(self.root)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def start(self) -> subprocess.CompletedProcess[str]:
        return self.run(
            "run",
            "--workflow",
            str(self.workflow),
            "--run-dir",
            str(self.run_dir),
            "--run-id",
            "r1",
            "--candidate-id",
            "candidate-r1",
        )


class ExecutableEvolutionLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v13-loop-")
        self.fixture = LoopFixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_run_executes_red_then_pauses_honestly_at_external_refinement(self) -> None:
        result = self.fixture.start()
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        state = json.loads((self.fixture.run_dir / "run-state.json").read_text(encoding="utf-8"))
        self.assertEqual("awaiting_external_action", state["status"])
        self.assertEqual("completed", state["steps"]["targeted_red"]["status"])
        self.assertEqual("waiting", state["steps"]["refinement"]["status"])
        receipt = self.fixture.run_dir / "receipts" / "targeted_red.json"
        self.assertTrue(receipt.is_file())
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(1, saved["exit_code"])
        self.assertEqual("red", saved["assertion"])
        self.assertTrue(saved["stdout_sha256"])

    def test_resume_is_idempotent_and_cannot_skip_external_work(self) -> None:
        self.fixture.start()
        before = (self.fixture.run_dir / "events.jsonl").read_bytes()
        result = self.fixture.run("resume", "--run-dir", str(self.fixture.run_dir))
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertEqual(before, (self.fixture.run_dir / "events.jsonl").read_bytes())
        self.assertFalse((self.fixture.run_dir / "receipts" / "targeted_green.json").exists())

    def test_external_receipt_unblocks_resume_and_green_executes_once(self) -> None:
        self.fixture.start()
        external = self.fixture.root / "evals" / "external" / "refinement.json"
        write_json(
            external,
            {
                "schema_version": "1.0",
                "run_id": "r1",
                "step_id": "refinement",
                "status": "completed",
                "summary": "runtime changed under frozen red tests",
                "evidence": [{"path": "scripts/green.py", "sha256": digest(self.fixture.root / "scripts" / "green.py")}],
            },
        )
        completed = self.fixture.run(
            "complete-external",
            "--run-dir",
            str(self.fixture.run_dir),
            "--step-id",
            "refinement",
            "--receipt",
            str(external),
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        resumed = self.fixture.run("resume", "--run-dir", str(self.fixture.run_dir))
        self.assertEqual(0, resumed.returncode, resumed.stdout + resumed.stderr)
        state = json.loads((self.fixture.run_dir / "run-state.json").read_text(encoding="utf-8"))
        self.assertEqual("complete", state["status"])
        self.assertEqual("completed", state["steps"]["targeted_green"]["status"])
        events_before = (self.fixture.run_dir / "events.jsonl").read_bytes()
        again = self.fixture.run("resume", "--run-dir", str(self.fixture.run_dir))
        self.assertEqual(0, again.returncode, again.stdout + again.stderr)
        self.assertEqual(events_before, (self.fixture.run_dir / "events.jsonl").read_bytes())

    def test_workflow_drift_and_unsafe_python_c_are_rejected(self) -> None:
        self.fixture.start()
        workflow = json.loads(self.fixture.workflow.read_text(encoding="utf-8"))
        workflow["steps"][2]["expected"] = "red"
        write_json(self.fixture.workflow, workflow)
        drift = self.fixture.run("resume", "--run-dir", str(self.fixture.run_dir))
        self.assertEqual(3, drift.returncode, drift.stdout + drift.stderr)
        self.assertIn("evolution_workflow_drift", set(payload(drift).get("errors", [])))

        unsafe_root = Path(self.temporary.name) / "unsafe"
        unsafe = LoopFixture(unsafe_root)
        workflow = json.loads(unsafe.workflow.read_text(encoding="utf-8"))
        workflow["steps"][0]["argv"] = ["{python}", "-c", "print('fake')"]
        write_json(unsafe.workflow, workflow)
        rejected = unsafe.start()
        self.assertEqual(3, rejected.returncode, rejected.stdout + rejected.stderr)
        self.assertIn("evolution_argv_unsafe", set(payload(rejected).get("errors", [])))
        self.assertFalse(unsafe.run_dir.exists())


class AddOnlyTestManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v13-manifest-")
        self.root = Path(self.temporary.name)
        (self.root / "tests").mkdir(parents=True)
        (self.root / "evals" / "test-migrations").mkdir(parents=True)
        self.old = self.root / "tests" / "test_v12_old.py"
        self.old.write_text("# old contract\n", encoding="utf-8")
        self.manifest = self.root / "evals" / "test-generation-manifest.json"
        write_json(
            self.manifest,
            {
                "schema_version": "1.0",
                "generation_rules": [{"generation": "v12", "minimum": 1, "pattern": "tests/test_v12_*.py"}],
                "files": [{"generation": "v12", "path": "tests/test_v12_old.py", "sha256": digest(self.old)}],
            },
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def controller(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CONTROLLER),
                *args,
                "--root",
                str(self.root),
                "--test-manifest",
                str(self.manifest),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_sync_refuses_existing_hash_change_without_touching_manifest(self) -> None:
        before = self.manifest.read_bytes()
        self.old.write_text("# weakened contract\n", encoding="utf-8")
        result = self.controller("sync-tests")
        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("test_manifest_refuses_hash_change:tests/test_v12_old.py", set(payload(result).get("errors", [])))
        self.assertEqual(before, self.manifest.read_bytes())

    def test_explicit_migration_receipt_preserves_old_hash_and_is_rehashed(self) -> None:
        old_hash = digest(self.old)
        self.old.write_text("# corrected contract\n", encoding="utf-8")
        replacement = self.root / "tests" / "test_v13_replacement.py"
        replacement.write_text("# frozen replacement red contract\n", encoding="utf-8")
        evidence = self.root / "evals" / "architecture-finding.md"
        evidence.write_text("independent finding\n", encoding="utf-8")
        receipt = self.root / "evals" / "test-migrations" / "m1.json"
        write_json(
            receipt,
            {
                "schema_version": "1.0",
                "receipt_id": "m1",
                "test_path": "tests/test_v12_old.py",
                "from_sha256": old_hash,
                "to_sha256": digest(self.old),
                "reason": "old assertion encoded the audited release-gate bypass",
                "replacement_tests": [{"path": "tests/test_v13_replacement.py", "sha256": digest(replacement)}],
                "evidence": [{"path": "evals/architecture-finding.md", "sha256": digest(evidence)}],
                "reviewed_by": "independent-architecture-audit",
                "reviewed_at": "2026-08-07T00:00:00Z",
            },
        )
        result = self.controller("migrate-test", "--receipt", str(receipt))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        record = next(item for item in manifest["files"] if item["path"] == "tests/test_v12_old.py")
        self.assertEqual(digest(self.old), record["sha256"])
        self.assertEqual(old_hash, record["migration_history"][0]["from_sha256"])
        self.assertEqual(digest(receipt), record["migration_history"][0]["receipt_sha256"])

        receipt_data = json.loads(receipt.read_text(encoding="utf-8"))
        receipt_data["reason"] = "tampered later"
        write_json(receipt, receipt_data)
        checked = self.controller("sync-tests")
        self.assertEqual(3, checked.returncode, checked.stdout + checked.stderr)
        self.assertIn("test_migration_receipt_hash_mismatch", set(payload(checked).get("errors", [])))


if __name__ == "__main__":
    unittest.main()
