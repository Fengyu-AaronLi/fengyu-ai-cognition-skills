#!/usr/bin/env python3
"""V15 red contracts for failed-command receipt and state projection integrity."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts" / "run_evolution.py"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout) if result.stdout.strip() else {}


class FailedRunFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "scripts").mkdir(parents=True)
        (root / "workflows").mkdir()
        (root / "evals" / "runs").mkdir(parents=True)
        self.worker = root / "scripts" / "worker.py"
        self.worker.write_text(
            "print('worker did not satisfy the green contract')\nraise SystemExit(1)\n",
            encoding="utf-8",
        )
        self.workflow = root / "workflows" / "failed.json"
        write_json(
            self.workflow,
            {
                "schema_version": "1.0",
                "workflow_id": "identity-v15-failed-receipt",
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
        self.run_dir = root / "evals" / "runs" / "failed"

    def controller(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CONTROLLER), *args, "--root", str(self.root)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def start(self) -> None:
        result = self.controller(
            "run",
            "--workflow",
            str(self.workflow),
            "--run-dir",
            str(self.run_dir),
            "--run-id",
            "failed",
            "--candidate-id",
            "candidate-failed",
        )
        if result.returncode != 2:
            raise AssertionError(result.stdout + result.stderr)


class FailedReceiptIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v15-failed-")
        self.fixture = FailedRunFixture(Path(self.temporary.name))
        self.fixture.start()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_failed_command_receipt_and_raw_output_are_still_hash_verified(self) -> None:
        receipt = self.fixture.run_dir / "receipts" / "green.json"
        raw = self.fixture.run_dir / "raw" / "green.stdout.txt"
        receipt.write_text(receipt.read_text(encoding="utf-8") + " ", encoding="utf-8")
        checked = self.fixture.controller("status", "--run-dir", str(self.fixture.run_dir))
        self.assertEqual(3, checked.returncode, checked.stdout + checked.stderr)
        self.assertIn(
            "evolution_receipt_hash_mismatch",
            set(payload(checked).get("errors", [])),
        )

        # Restore the receipt from a fresh run, then prove raw output is bound too.
        second = FailedRunFixture(Path(self.temporary.name) / "second")
        second.start()
        second_raw = second.run_dir / "raw" / "green.stdout.txt"
        second_raw.write_text("forged green output\n", encoding="utf-8")
        raw_checked = second.controller("status", "--run-dir", str(second.run_dir))
        self.assertEqual(3, raw_checked.returncode, raw_checked.stdout + raw_checked.stderr)
        self.assertIn(
            "evolution_raw_output_hash_mismatch",
            set(payload(raw_checked).get("errors", [])),
        )

    def test_state_cannot_promote_a_failed_receipt_to_completed(self) -> None:
        state_path = self.fixture.run_dir / "run-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["steps"]["green"]["status"] = "completed"
        state["status"] = "complete"
        state["current_step"] = None
        write_json(state_path, state)

        checked = self.fixture.controller("status", "--run-dir", str(self.fixture.run_dir))
        self.assertEqual(3, checked.returncode, checked.stdout + checked.stderr)
        self.assertIn(
            "evolution_step_projection_invalid",
            set(payload(checked).get("errors", [])),
        )


if __name__ == "__main__":
    unittest.main()
