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
from unittest.mock import patch


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import improvement_loop  # noqa: E402
import test_round87_finding_closure_ledger_red as round87  # noqa: E402
import test_round90_controller_state_integrity_red as round90  # noqa: E402


class Round93SourceEpochRedTests(unittest.TestCase):
    """A RED/GREEN phase must prove one authorized before-to-after source epoch."""

    def _state_before_fix(self, root: Path):
        helper = round87.Round87FindingClosureLedgerRedTests()
        graph, paths, state, finding = helper.open_finding(root)
        state = helper.record_plain(graph, paths, state, "preflight_snapshot")
        state = helper.record_plain(graph, paths, state, "adversarial_review")
        return helper, graph, paths, state, finding

    def test_open_finding_cannot_claim_fix_after_unplanned_source_change(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round93-unplanned-") as temp_dir:
            _, graph, paths, state, _ = self._state_before_fix(Path(temp_dir))
            receipt, _ = graph.write_receipt(paths, state, "red_green_fix")
            graph.begin_and_bind(paths, "red_green_fix", receipt)
            paths["skill_file"].write_text(
                paths["skill_file"].read_text(encoding="utf-8")
                + "\nunplanned fix\n",
                encoding="utf-8",
            )
            with self.assertRaises(improvement_loop.LoopError) as raised:
                improvement_loop.command_record_step(
                    argparse.Namespace(
                        state_dir=str(paths["state_dir"]),
                        step_id="red_green_fix",
                        receipt=receipt.relative_to(paths["repo"]).as_posix(),
                    )
                )
            self.assertEqual(
                "SOURCE_EPOCH_AUTHORIZATION_REQUIRED", raised.exception.code
            )

    def test_authorized_fix_commits_distinct_before_and_after_sources(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round93-commit-") as temp_dir:
            _, graph, paths, state, finding = self._state_before_fix(Path(temp_dir))
            controller = round90.Round90ControllerStateIntegrityRedTests()
            controller.setUp()
            receipt = controller._write_typed_fix_receipt(
                graph, paths, state, finding["finding_id"]
            )
            updated = graph.record(paths, "red_green_fix", receipt)
            iteration = updated["iterations"][-1]
            epoch = iteration["source_epoch"]
            self.assertIsNone(iteration["pending_source_epoch"])
            self.assertNotEqual(
                epoch["source_before_sha256"], epoch["source_after_sha256"]
            )
            self.assertEqual(
                epoch["source_after_sha256"], iteration["active_source_sha256"]
            )
            self.assertEqual(
                epoch["source_after_sha256"], updated["source_snapshot"]["sha256"]
            )
            self.assertEqual(
                epoch["source_after_sha256"],
                iteration["step_ledger"][-1]["source_sha256"],
            )

    def test_retained_after_blob_tamper_breaks_state_loading(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round93-blob-") as temp_dir:
            helper, graph, paths, state, _ = self._state_before_fix(Path(temp_dir))
            state = helper.authorize_fixture_fix(graph, paths, state)
            pending = state["iterations"][-1]["pending_source_epoch"]
            blob = (
                paths["repo"]
                / pending["implementation_changes"][0]["after_blob"]["path"]
            )
            blob.write_text(blob.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
            with self.assertRaises(improvement_loop.LoopError) as raised:
                improvement_loop.load_state(paths["state_dir"])
            self.assertEqual("STATE_EVIDENCE_INVALID", raised.exception.code)

    def test_plan_does_not_authorize_an_extra_live_change(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round93-extra-") as temp_dir:
            helper, graph, paths, state, finding = self._state_before_fix(Path(temp_dir))
            state = helper.authorize_fixture_fix(graph, paths, state)
            controller = round90.Round90ControllerStateIntegrityRedTests()
            controller.setUp()
            receipt = controller._write_typed_fix_receipt(
                graph, paths, state, finding["finding_id"]
            )
            producer = paths["controller"].with_name("produce_release_gate.py")
            producer.write_text(
                producer.read_text(encoding="utf-8") + "\nextra drift\n",
                encoding="utf-8",
            )
            with self.assertRaises(improvement_loop.LoopError) as raised:
                graph.record(paths, "red_green_fix", receipt)
            self.assertEqual("SOURCE_EPOCH_AFTER_MISMATCH", raised.exception.code)

    def test_authorized_epoch_must_claim_every_bound_finding(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round93-coverage-") as temp_dir:
            helper, graph, paths, state, _ = self._state_before_fix(Path(temp_dir))
            state = helper.authorize_fixture_fix(graph, paths, state)
            accepted = {
                entry["step_id"]: entry["receipt"]["sha256"]
                for entry in state["iterations"][-1]["step_ledger"]
            }
            receipt, _ = graph.write_receipt(
                paths,
                state,
                "red_green_fix",
                dependency_receipts={
                    "adversarial_review": accepted["adversarial_review"]
                },
            )
            with self.assertRaises(improvement_loop.LoopError) as raised:
                graph.record(paths, "red_green_fix", receipt)
            self.assertEqual("SOURCE_EPOCH_FINDING_MISMATCH", raised.exception.code)

    def test_fix_commit_crash_resumes_exactly_once_on_authorized_after_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round93-resume-") as temp_dir:
            _, graph, paths, state, finding = self._state_before_fix(Path(temp_dir))
            controller = round90.Round90ControllerStateIntegrityRedTests()
            controller.setUp()
            receipt = controller._write_typed_fix_receipt(
                graph, paths, state, finding["finding_id"]
            )
            with patch.dict(
                os.environ,
                {"SFFS_IMPROVEMENT_LOOP_FAILPOINT": "after_prepare"},
            ):
                with self.assertRaises(improvement_loop.LoopError) as crashed:
                    graph.record(paths, "red_green_fix", receipt)
            self.assertEqual("SIMULATED_CRASH", crashed.exception.code)

            with redirect_stdout(StringIO()):
                improvement_loop.command_resume(
                    argparse.Namespace(state_dir=str(paths["state_dir"]))
                )
            recovered = json.loads(
                (paths["state_dir"] / improvement_loop.STATE_FILE).read_text(
                    encoding="utf-8"
                )
            )
            self.assertIsNotNone(recovered["iterations"][-1]["source_epoch"])
            self.assertIsNone(recovered["iterations"][-1]["pending_source_epoch"])
            self.assertIsNotNone(
                recovered["finding_ledger"][finding["finding_id"]]["fix"]
            )
            before_repeat = improvement_loop.canonical_sha256(recovered)
            with redirect_stdout(StringIO()):
                improvement_loop.command_resume(
                    argparse.Namespace(state_dir=str(paths["state_dir"]))
                )
            repeated = json.loads(
                (paths["state_dir"] / improvement_loop.STATE_FILE).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(before_repeat, improvement_loop.canonical_sha256(repeated))

    def test_fix_commit_crash_plus_unplanned_s2_does_not_publish_the_fix(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round93-abort-") as temp_dir:
            _, graph, paths, state, finding = self._state_before_fix(Path(temp_dir))
            controller = round90.Round90ControllerStateIntegrityRedTests()
            controller.setUp()
            receipt = controller._write_typed_fix_receipt(
                graph, paths, state, finding["finding_id"]
            )
            with patch.dict(
                os.environ,
                {"SFFS_IMPROVEMENT_LOOP_FAILPOINT": "after_prepare"},
            ):
                with self.assertRaises(improvement_loop.LoopError):
                    graph.record(paths, "red_green_fix", receipt)
            paths["skill_file"].write_text(
                paths["skill_file"].read_text(encoding="utf-8")
                + "\nunplanned S2\n",
                encoding="utf-8",
            )
            with redirect_stdout(StringIO()):
                improvement_loop.command_resume(
                    argparse.Namespace(state_dir=str(paths["state_dir"]))
                )
            recovered = json.loads(
                (paths["state_dir"] / improvement_loop.STATE_FILE).read_text(
                    encoding="utf-8"
                )
            )
            finding_state = recovered["finding_ledger"][finding["finding_id"]]
            self.assertEqual("open", finding_state["status"])
            self.assertIsNone(finding_state["fix"])
            self.assertIn(
                finding["finding_id"],
                recovered["iterations"][-1]["carried_findings"],
            )
            self.assertTrue(
                list(
                    (paths["state_dir"] / "transactions").glob("*-aborted.json")
                )
            )

    def test_unhashable_state_values_fail_closed_as_loop_errors(self) -> None:
        mutations = (
            (
                "epoch-finding-ids",
                lambda state: state["iterations"][-1]["pending_source_epoch"].update(
                    {"finding_ids": [{}]}
                ),
            ),
            (
                "denied-operations",
                lambda state: state["workflow_policy"].update(
                    {"denied_operations": [{}]}
                ),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory(
                prefix=f"sffs-round93-unhashable-{label}-"
            ) as temp_dir:
                helper, graph, paths, state, _ = self._state_before_fix(
                    Path(temp_dir)
                )
                state = helper.authorize_fixture_fix(graph, paths, state)
                mutate(state)
                (paths["state_dir"] / improvement_loop.STATE_FILE).write_text(
                    json.dumps(state, indent=2) + "\n", encoding="utf-8"
                )
                with self.assertRaises(improvement_loop.LoopError) as raised:
                    improvement_loop.load_state(paths["state_dir"])
                self.assertEqual("STATE_INVALID", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
