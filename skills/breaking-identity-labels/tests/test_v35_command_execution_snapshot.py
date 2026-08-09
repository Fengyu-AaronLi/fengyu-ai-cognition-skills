#!/usr/bin/env python3
"""V35 contracts for script and declared-input execution snapshots."""

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


class SnapshotFixture:
    def __init__(self, root: Path, *, include_inputs: bool = True) -> None:
        self.root = root
        for relative in ("scripts", "workflows", "evals/runs", "inputs"):
            (root / relative).mkdir(parents=True, exist_ok=True)
        self.worker = root / "scripts" / "worker.py"
        self.worker.write_text("print('snapshot worker passed')\n", encoding="utf-8")
        (root / "inputs" / "a.txt").write_text("alpha\n", encoding="utf-8")
        (root / "inputs" / "z.txt").write_text("omega\n", encoding="utf-8")
        command = {
            "id": "green",
            "kind": "command",
            "depends_on": [],
            "argv": ["{python}", "{root}/scripts/worker.py"],
            "expected": "exit_zero",
        }
        if include_inputs:
            command["input_files"] = [
                "{root}/inputs/z.txt",
                "inputs/a.txt",
            ]
        self.workflow = root / "workflows" / "snapshot.json"
        write_json(
            self.workflow,
            {
                "schema_version": "1.0",
                "workflow_id": "identity-v35-command-snapshot",
                "steps": [command],
            },
        )
        self.run_dir = root / "evals" / "runs" / "snapshot"

    def controller(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CONTROLLER), *args, "--root", str(self.root)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def start(self) -> subprocess.CompletedProcess[str]:
        return self.controller(
            "run",
            "--workflow",
            str(self.workflow),
            "--run-dir",
            str(self.run_dir),
            "--run-id",
            "v35-snapshot",
            "--candidate-id",
            "candidate-v35",
        )

    def status(self) -> subprocess.CompletedProcess[str]:
        return self.controller("status", "--run-dir", str(self.run_dir))


class CommandExecutionSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v35-snapshot-")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_receipt_binds_script_controlled_environment_and_sorted_inputs(self) -> None:
        fixture = SnapshotFixture(Path(self.temporary.name))
        result = fixture.start()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

        receipt = json.loads(
            (fixture.run_dir / "receipts" / "green.json").read_text(encoding="utf-8")
        )
        self.assertEqual("scripts/worker.py", receipt["script_path"])
        self.assertEqual(digest(fixture.worker), receipt["script_sha256"])
        self.assertEqual(".", receipt["input_snapshot"]["cwd"])
        self.assertEqual(
            {"PYTHONHASHSEED": "0"},
            receipt["input_snapshot"]["environment"],
        )
        self.assertEqual(
            ["inputs/a.txt", "inputs/z.txt"],
            [item["path"] for item in receipt["input_snapshot"]["files"]],
        )

    def test_workflow_without_declared_inputs_records_an_explicit_empty_snapshot(self) -> None:
        fixture = SnapshotFixture(Path(self.temporary.name), include_inputs=False)
        result = fixture.start()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        receipt = json.loads(
            (fixture.run_dir / "receipts" / "green.json").read_text(encoding="utf-8")
        )
        self.assertEqual([], receipt["input_snapshot"]["files"])

    def test_status_rejects_script_bytes_changed_after_execution(self) -> None:
        fixture = SnapshotFixture(Path(self.temporary.name))
        self.assertEqual(0, fixture.start().returncode)
        fixture.worker.write_text("print('changed after execution')\n", encoding="utf-8")

        checked = fixture.status()

        self.assertEqual(3, checked.returncode, checked.stdout + checked.stderr)
        self.assertIn("evolution_command_script_hash_mismatch", errors(checked))

    def test_status_rejects_declared_input_changed_after_execution(self) -> None:
        fixture = SnapshotFixture(Path(self.temporary.name))
        self.assertEqual(0, fixture.start().returncode)
        (fixture.root / "inputs" / "a.txt").write_text("changed\n", encoding="utf-8")

        checked = fixture.status()

        self.assertEqual(3, checked.returncode, checked.stdout + checked.stderr)
        self.assertIn("evolution_command_input_hash_mismatch", errors(checked))

    def test_missing_or_unsafe_inputs_are_rejected_before_command_execution(self) -> None:
        fixture = SnapshotFixture(Path(self.temporary.name))
        workflow = json.loads(fixture.workflow.read_text(encoding="utf-8"))
        workflow["steps"][0]["input_files"] = ["inputs/missing.txt"]
        write_json(fixture.workflow, workflow)
        missing = fixture.start()
        self.assertEqual(3, missing.returncode, missing.stdout + missing.stderr)
        self.assertIn("evolution_command_input_unavailable", errors(missing))
        self.assertFalse((fixture.run_dir / "receipts" / "green.json").exists())

        unsafe_root = Path(self.temporary.name) / "unsafe"
        unsafe = SnapshotFixture(unsafe_root)
        workflow = json.loads(unsafe.workflow.read_text(encoding="utf-8"))
        workflow["steps"][0]["input_files"] = ["../outside.txt"]
        write_json(unsafe.workflow, workflow)
        rejected = unsafe.start()
        self.assertEqual(3, rejected.returncode, rejected.stdout + rejected.stderr)
        self.assertIn("evolution_input_file_unsafe_path", errors(rejected))
        self.assertFalse(unsafe.run_dir.exists())

    def test_a_previous_command_may_generate_a_later_declared_run_input(self) -> None:
        root = Path(self.temporary.name)
        for relative in ("scripts", "workflows", "evals/runs"):
            (root / relative).mkdir(parents=True, exist_ok=True)
        (root / "scripts" / "generate.py").write_text(
            "from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('generated\\n')\n",
            encoding="utf-8",
        )
        (root / "scripts" / "consume.py").write_text("print('consumed')\n", encoding="utf-8")
        workflow = root / "workflows" / "generated-input.json"
        write_json(
            workflow,
            {
                "schema_version": "1.0",
                "workflow_id": "identity-v35-generated-input",
                "steps": [
                    {
                        "id": "generate",
                        "kind": "command",
                        "depends_on": [],
                        "argv": [
                            "{python}",
                            "{root}/scripts/generate.py",
                            "{run_dir}/generated.txt",
                        ],
                        "expected": "exit_zero",
                    },
                    {
                        "id": "consume",
                        "kind": "command",
                        "depends_on": ["generate"],
                        "argv": ["{python}", "{root}/scripts/consume.py"],
                        "input_files": ["{run_dir}/generated.txt"],
                        "expected": "exit_zero",
                    },
                ],
            },
        )
        run_dir = root / "evals" / "runs" / "generated"
        result = subprocess.run(
            [
                sys.executable,
                str(CONTROLLER),
                "run",
                "--workflow",
                str(workflow),
                "--run-dir",
                str(run_dir),
                "--run-id",
                "v35-generated",
                "--candidate-id",
                "candidate-v35-generated",
                "--root",
                str(root),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
