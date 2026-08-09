#!/usr/bin/env python3
"""Round 156: controller-owned run-next and host receipt integrity."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import improvement_loop  # noqa: E402
import test_round86_workflow_step_ledger_red as round86  # noqa: E402


class Round156ControllerOwnedRunnerRedTests(unittest.TestCase):
    def test_run_next_executes_only_the_real_next_step_and_records_host_bytes(self) -> None:
        helper = round86.Round86WorkflowStepLedgerRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round156-runner-") as temp_dir:
            paths, _ = helper.make_graph_candidate(Path(temp_dir))
            output = StringIO()
            with redirect_stdout(output):
                result = improvement_loop.command_run_next(
                    argparse.Namespace(state_dir=str(paths["state_dir"]))
                )
            self.assertEqual(0, result)
            emitted = json.loads(output.getvalue())
            iteration = emitted["iterations"][-1]
            self.assertEqual("adversarial_review", iteration["next_step"])
            self.assertIsNone(iteration["active_work_order"])
            self.assertEqual(1, len(iteration["step_ledger"]))
            entry = iteration["step_ledger"][0]
            self.assertEqual("preflight_snapshot", entry["step_id"])
            roles = {artifact["role"] for artifact in entry["artifacts"]}
            self.assertEqual(
                {
                    "preflight_report",
                    "host_execution_receipt",
                    "worker_stdout",
                    "worker_stderr",
                },
                roles,
            )
            host_ref = next(
                item
                for item in entry["artifacts"]
                if item["role"] == "host_execution_receipt"
            )
            host = json.loads(
                (paths["repo"] / host_ref["path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(
                improvement_loop.GRAPH_RUNNER_TRUST_BOUNDARY,
                host["trust_boundary"],
            )
            self.assertIs(host["command"]["shell"], False)
            self.assertEqual(0, host["process"]["exit_code"])
            self.assertTrue(host["process"]["process_family"]["confirmed_empty"])

    def test_cli_exposes_no_step_command_or_argv_override(self) -> None:
        parsed = improvement_loop.parser().parse_args(
            ["run-next", "--state-dir", "/tmp/fixed-state"]
        )
        self.assertEqual("run-next", parsed.command)
        for forbidden in ("--step-id", "--command", "--argv", "--shell"):
            with self.subTest(forbidden=forbidden), redirect_stderr(StringIO()):
                with self.assertRaises(improvement_loop.LoopError) as raised:
                    improvement_loop.parser().parse_args(
                        [
                            "run-next",
                            "--state-dir",
                            "/tmp/fixed-state",
                            forbidden,
                            "attacker-value",
                        ]
                    )
                self.assertEqual("ARGUMENT_ERROR", raised.exception.code)

    def test_tampered_worker_stdout_invalidates_persisted_state(self) -> None:
        helper = round86.Round86WorkflowStepLedgerRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round156-tamper-") as temp_dir:
            paths, _ = helper.make_graph_candidate(Path(temp_dir))
            with redirect_stdout(StringIO()):
                improvement_loop.command_run_next(
                    argparse.Namespace(state_dir=str(paths["state_dir"]))
                )
            state = json.loads(
                (paths["state_dir"] / "loop-state.json").read_text(encoding="utf-8")
            )
            entry = state["iterations"][-1]["step_ledger"][0]
            stdout_ref = next(
                item for item in entry["artifacts"] if item["role"] == "worker_stdout"
            )
            (paths["repo"] / stdout_ref["path"]).write_text(
                "{}\n", encoding="utf-8"
            )
            with self.assertRaises(improvement_loop.LoopError):
                improvement_loop.load_state(paths["state_dir"])


if __name__ == "__main__":
    unittest.main()
