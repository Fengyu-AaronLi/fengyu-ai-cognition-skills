#!/usr/bin/env python3
"""Round 157 RED: a retained host result is replayed, never re-executed."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import improvement_loop  # noqa: E402
import test_round86_workflow_step_ledger_red as round86  # noqa: E402


class Round157RunnerRecoveryRedTests(unittest.TestCase):
    def test_crash_after_host_receipt_replays_exact_bytes_once(self) -> None:
        helper = round86.Round86WorkflowStepLedgerRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round157-recovery-") as temp_dir:
            paths, _ = helper.make_graph_candidate(Path(temp_dir))
            with mock.patch.dict(
                os.environ,
                {"SFFS_GRAPH_RUNNER_FAILPOINT": "after_host_receipt"},
                clear=False,
            ):
                with self.assertRaises(improvement_loop.LoopError) as raised:
                    with redirect_stdout(StringIO()):
                        improvement_loop.command_run_next(
                            argparse.Namespace(state_dir=str(paths["state_dir"]))
                        )
            self.assertEqual("SIMULATED_RUNNER_CRASH", raised.exception.code)
            state = json.loads(
                (paths["state_dir"] / "loop-state.json").read_text(encoding="utf-8")
            )
            active = state["iterations"][-1]["active_work_order"]
            execution_dir = next((paths["state_dir"] / "executions").iterdir())
            host_path = execution_dir / "host-execution-receipt.json"
            host_sha = improvement_loop.file_sha256(host_path)
            stdout_sha = improvement_loop.file_sha256(execution_dir / "stdout.json")
            self.assertEqual("preflight_snapshot", active["step_id"])

            output = StringIO()
            with redirect_stdout(output):
                improvement_loop.command_run_next(
                    argparse.Namespace(state_dir=str(paths["state_dir"]))
                )
            recovered = json.loads(output.getvalue())
            self.assertEqual(
                "adversarial_review", recovered["iterations"][-1]["next_step"]
            )
            self.assertEqual(host_sha, improvement_loop.file_sha256(host_path))
            self.assertEqual(
                stdout_sha,
                improvement_loop.file_sha256(execution_dir / "stdout.json"),
            )
            self.assertEqual(
                1,
                len(list((paths["state_dir"] / "executions").iterdir())),
                "recovery must not start a second execution",
            )


if __name__ == "__main__":
    unittest.main()
