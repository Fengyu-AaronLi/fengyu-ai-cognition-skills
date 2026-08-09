from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import improvement_loop  # noqa: E402
import test_round86_workflow_step_ledger_red as round86  # noqa: E402


class Round91RunBoundWorkOrdersRedTests(unittest.TestCase):
    """External phase evidence needs a controller-issued, run-local nonce."""

    def _start_second_run(self, paths: dict[str, Path]) -> dict:
        manifest = json.loads(paths["source_manifest"].read_text(encoding="utf-8"))
        governance = {
            paths["workflow"].relative_to(paths["repo"]).as_posix(),
            paths["controller"].relative_to(paths["repo"]).as_posix(),
            paths["source_manifest"].relative_to(paths["repo"]).as_posix(),
        }
        source_files = [
            item for item in manifest["source_files"] if item not in governance
        ]
        with redirect_stdout(StringIO()):
            improvement_loop.command_start(
                argparse.Namespace(
                    repo_root=str(paths["repo"]),
                    workflow="workflows/separating-facts-loop.yaml",
                    state_dir=".ao-output/loop-run-b",
                    source_file=source_files,
                    allow_write=[
                        "skills/separating-facts-from-stories",
                        "workflows",
                        ".ao-output",
                    ],
                    max_rounds=3,
                )
            )
        return json.loads(
            (
                paths["repo"]
                / ".ao-output"
                / "loop-run-b"
                / improvement_loop.STATE_FILE
            ).read_text(encoding="utf-8")
        )

    def test_record_step_requires_a_controller_issued_work_order(self) -> None:
        helper = round86.Round86WorkflowStepLedgerRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round91-order-") as temp_dir:
            paths, state = helper.make_graph_candidate(Path(temp_dir))
            receipt, _ = helper.write_receipt(
                paths, state, "preflight_snapshot"
            )
            with self.assertRaises(improvement_loop.LoopError) as raised:
                improvement_loop.command_record_step(
                    argparse.Namespace(
                        state_dir=str(paths["state_dir"]),
                        step_id="preflight_snapshot",
                        receipt=receipt.relative_to(paths["repo"]).as_posix(),
                    )
                )
            self.assertEqual("WORK_ORDER_REQUIRED", raised.exception.code)

    def test_phase_receipt_from_another_controller_run_is_rejected(self) -> None:
        helper = round86.Round86WorkflowStepLedgerRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round91-replay-") as temp_dir:
            paths, run_a = helper.make_graph_candidate(Path(temp_dir))
            run_b = self._start_second_run(paths)
            self.assertEqual(
                run_a["iterations"][-1]["iteration_id"],
                run_b["iterations"][-1]["iteration_id"],
            )
            self.assertNotEqual(
                run_a["controller_run_id"], run_b["controller_run_id"]
            )

            receipt_a, _ = helper.write_receipt(
                paths, run_a, "preflight_snapshot"
            )
            helper.begin_and_bind(paths, "preflight_snapshot", receipt_a)
            run_b_dir = paths["repo"] / ".ao-output" / "loop-run-b"
            with redirect_stdout(StringIO()):
                improvement_loop.command_begin_step(
                    argparse.Namespace(
                        state_dir=str(run_b_dir),
                        step_id="preflight_snapshot",
                    )
                )
            replay_path = run_b_dir / "replayed-preflight.receipt.json"
            replay_path.write_bytes(receipt_a.read_bytes())

            with self.assertRaises(improvement_loop.LoopError) as raised:
                improvement_loop.command_record_step(
                    argparse.Namespace(
                        state_dir=str(run_b_dir),
                        step_id="preflight_snapshot",
                        receipt=replay_path.relative_to(paths["repo"]).as_posix(),
                    )
                )
            self.assertEqual("RUN_ID_MISMATCH", raised.exception.code)

    def test_begin_step_retry_returns_the_same_unconsumed_attempt(self) -> None:
        helper = round86.Round86WorkflowStepLedgerRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round91-idempotent-") as temp_dir:
            paths, _ = helper.make_graph_candidate(Path(temp_dir))
            for _ in range(2):
                with redirect_stdout(StringIO()):
                    improvement_loop.command_begin_step(
                        argparse.Namespace(
                            state_dir=str(paths["state_dir"]),
                            step_id="preflight_snapshot",
                        )
                    )
                state = json.loads(
                    (paths["state_dir"] / improvement_loop.STATE_FILE).read_text(
                        encoding="utf-8"
                    )
                )
                if _ == 0:
                    first = dict(state["iterations"][-1]["active_work_order"])
            self.assertEqual(first, state["iterations"][-1]["active_work_order"])
            self.assertEqual(
                1,
                len(list((paths["state_dir"] / "work-orders").glob("*.json"))),
            )

    def test_work_order_tamper_breaks_persisted_state_loading(self) -> None:
        helper = round86.Round86WorkflowStepLedgerRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round91-tamper-") as temp_dir:
            paths, state = helper.make_graph_candidate(Path(temp_dir))
            receipt, _ = helper.write_receipt(
                paths, state, "preflight_snapshot"
            )
            helper.begin_and_bind(paths, "preflight_snapshot", receipt)
            current = json.loads(
                (paths["state_dir"] / improvement_loop.STATE_FILE).read_text(
                    encoding="utf-8"
                )
            )
            active = current["iterations"][-1]["active_work_order"]
            work_order = paths["repo"] / active["path"]
            work_order.write_text(
                work_order.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(improvement_loop.LoopError) as raised:
                improvement_loop.load_state(paths["state_dir"])
            self.assertEqual("STATE_EVIDENCE_INVALID", raised.exception.code)

    def test_receipt_cannot_change_the_controller_attempt_nonce(self) -> None:
        helper = round86.Round86WorkflowStepLedgerRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round91-nonce-") as temp_dir:
            paths, state = helper.make_graph_candidate(Path(temp_dir))
            receipt, _ = helper.write_receipt(
                paths, state, "preflight_snapshot"
            )
            helper.begin_and_bind(paths, "preflight_snapshot", receipt)
            document = json.loads(receipt.read_text(encoding="utf-8"))
            document["attempt_id"] = "attempt-attacker-relabelled"
            receipt.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(improvement_loop.LoopError) as raised:
                improvement_loop.command_record_step(
                    argparse.Namespace(
                        state_dir=str(paths["state_dir"]),
                        step_id="preflight_snapshot",
                        receipt=receipt.relative_to(paths["repo"]).as_posix(),
                    )
                )
            self.assertEqual("STEP_RECEIPT_INVALID", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
