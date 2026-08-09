from __future__ import annotations

import argparse
import json
import os
import shutil
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
import test_round87_finding_closure_ledger_red as round87  # noqa: E402
import test_round94_graph_native_source_epoch_red as round94  # noqa: E402
import test_round59_retained_snapshot_and_process_family_red as round59  # noqa: E402


class Round95RecoveryAndRecheckRedTests(unittest.TestCase):
    """Every rejected transition needs a legal recovery edge."""

    @staticmethod
    def _state(paths: dict[str, Path]) -> dict:
        return json.loads(
            (paths["state_dir"] / improvement_loop.STATE_FILE).read_text(
                encoding="utf-8"
            )
        )

    def _resume(self, paths: dict[str, Path]) -> dict:
        with redirect_stdout(StringIO()):
            improvement_loop.command_resume(
                argparse.Namespace(state_dir=str(paths["state_dir"]))
            )
        return self._state(paths)

    def test_active_work_order_source_drift_resumes_into_one_new_round(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round95-work-order-") as temp_dir:
            graph = round86.Round86WorkflowStepLedgerRedTests()
            paths, state = graph.make_graph_candidate(Path(temp_dir))
            receipt, _ = graph.write_receipt(paths, state, "preflight_snapshot")
            graph.begin_and_bind(paths, "preflight_snapshot", receipt)
            paths["skill_file"].write_text(
                paths["skill_file"].read_text(encoding="utf-8")
                + "\nsource drift after work order\n",
                encoding="utf-8",
            )

            with self.assertRaises(improvement_loop.LoopError) as raised:
                improvement_loop.command_record_step(
                    argparse.Namespace(
                        state_dir=str(paths["state_dir"]),
                        step_id="preflight_snapshot",
                        receipt=receipt.relative_to(paths["repo"]).as_posix(),
                    )
                )
            self.assertEqual(
                "SOURCE_DRIFT_INVALIDATED_STEPS", raised.exception.code
            )

            recovered = self._resume(paths)
            self.assertEqual(2, recovered["current_round"])
            self.assertEqual("LOOP", recovered["decision"])
            self.assertIsNone(recovered["iterations"][0]["active_work_order"])
            drift_id = "SOURCE-DRIFT-R001"
            self.assertEqual("open", recovered["finding_ledger"][drift_id]["status"])
            self.assertIn(drift_id, recovered["iterations"][-1]["carried_findings"])

            before_repeat = improvement_loop.canonical_sha256(recovered)
            repeated = self._resume(paths)
            self.assertEqual(
                before_repeat, improvement_loop.canonical_sha256(repeated)
            )

    def test_resume_preserves_an_authorized_intermediate_red_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round95-sr-") as temp_dir:
            native = round94.Round94GraphNativeSourceEpochRedTests()
            graph, _, paths, state, finding = native._open_graph_finding(
                Path(temp_dir)
            )
            state, _ = native._authorize_v2_epoch(
                graph, paths, state, finding["finding_id"]
            )
            epoch = state["iterations"][-1]["pending_source_epoch"]
            implementation = epoch["implementation_changes"][0]
            (paths["repo"] / implementation["path"]).write_bytes(
                (paths["repo"] / implementation["red_blob"]["path"]).read_bytes()
            )
            self.assertEqual(
                epoch["red_source_sha256"],
                improvement_loop.source_snapshot(
                    Path(state["repo_root"]), state["source_files"]
                )["sha256"],
            )

            before_resume = improvement_loop.canonical_sha256(self._state(paths))
            recovered = self._resume(paths)
            self.assertEqual(1, recovered["current_round"])
            self.assertIsNotNone(
                recovered["iterations"][-1]["active_work_order"]
            )
            self.assertIsNotNone(
                recovered["iterations"][-1]["pending_source_epoch"]
            )
            self.assertEqual(
                before_resume, improvement_loop.canonical_sha256(recovered)
            )

    def test_resume_preserves_an_authorized_after_source_ready_to_record(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round95-s1-") as temp_dir:
            native = round94.Round94GraphNativeSourceEpochRedTests()
            graph, _, paths, state, finding = native._open_graph_finding(
                Path(temp_dir)
            )
            state, _ = native._authorize_v2_epoch(
                graph, paths, state, finding["finding_id"]
            )
            epoch = state["iterations"][-1]["pending_source_epoch"]
            self.assertEqual(
                epoch["source_after_sha256"],
                improvement_loop.source_snapshot(
                    Path(state["repo_root"]), state["source_files"]
                )["sha256"],
            )

            before_resume = improvement_loop.canonical_sha256(self._state(paths))
            recovered = self._resume(paths)
            self.assertEqual(1, recovered["current_round"])
            self.assertIsNotNone(
                recovered["iterations"][-1]["pending_source_epoch"]
            )
            self.assertEqual(
                before_resume, improvement_loop.canonical_sha256(recovered)
            )

    def test_unplanned_s2_resumes_with_original_finding_still_open(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round95-s2-") as temp_dir:
            native = round94.Round94GraphNativeSourceEpochRedTests()
            graph, _, paths, state, finding = native._open_graph_finding(
                Path(temp_dir)
            )
            state, _ = native._authorize_v2_epoch(
                graph, paths, state, finding["finding_id"]
            )
            paths["skill_file"].write_text(
                paths["skill_file"].read_text(encoding="utf-8")
                + "\nunplanned S2\n",
                encoding="utf-8",
            )

            recovered = self._resume(paths)
            original = recovered["finding_ledger"][finding["finding_id"]]
            self.assertEqual(2, recovered["current_round"])
            self.assertEqual("open", original["status"])
            self.assertIsNone(original["fix"])
            self.assertIsNone(recovered["iterations"][0]["active_work_order"])
            self.assertIsNone(recovered["iterations"][0]["pending_source_epoch"])
            self.assertIn(
                finding["finding_id"],
                recovered["iterations"][-1]["carried_findings"],
            )

    def test_source_drift_supersedes_an_unclosed_fix_without_losing_audit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round95-fixed-s2-") as temp_dir:
            native = round94.Round94GraphNativeSourceEpochRedTests()
            graph, helper, paths, state, finding = native._open_graph_finding(
                Path(temp_dir)
            )
            state, _ = native._authorize_v2_epoch(
                graph, paths, state, finding["finding_id"]
            )
            state = native._record_fix(
                graph, helper, paths, state, finding["finding_id"]
            )
            old_fix = state["finding_ledger"][finding["finding_id"]]["fix"]
            paths["skill_file"].write_text(
                paths["skill_file"].read_text(encoding="utf-8")
                + "\nS2 after green before recheck\n",
                encoding="utf-8",
            )

            recovered = self._resume(paths)
            item = recovered["finding_ledger"][finding["finding_id"]]
            self.assertEqual(2, recovered["current_round"])
            self.assertEqual("open", item["status"])
            self.assertIsNone(item["fix"])
            self.assertEqual(1, len(item["superseded_fixes"]))
            self.assertEqual(
                old_fix["event_sha256"],
                item["superseded_fixes"][0]["event_sha256"],
            )
            self.assertEqual(
                recovered["source_snapshot"]["sha256"],
                item["superseded_fixes"][0]["superseded_by_source_sha256"],
            )

    def test_source_drift_that_changes_historical_red_evidence_requires_fresh_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round95-red-s2-") as temp_dir:
            native = round94.Round94GraphNativeSourceEpochRedTests()
            graph, helper, paths, state, finding = native._open_graph_finding(
                Path(temp_dir)
            )
            state, _ = native._authorize_v2_epoch(
                graph, paths, state, finding["finding_id"]
            )
            state = native._record_fix(
                graph, helper, paths, state, finding["finding_id"]
            )
            paths["red_test"].write_text(
                paths["red_test"].read_text(encoding="utf-8")
                + "\n# unplanned S2 changed the old RED file\n",
                encoding="utf-8",
            )

            with self.assertRaises(improvement_loop.LoopError) as raised:
                self._resume(paths)
            self.assertEqual("STATE_EVIDENCE_INVALID", raised.exception.code)
            unchanged = self._state(paths)
            self.assertEqual(1, unchanged["current_round"])
            self.assertIsNotNone(
                unchanged["finding_ledger"][finding["finding_id"]]["fix"]
            )

    def test_retained_stop_resume_survives_a_missing_live_source_file(self) -> None:
        producer = round59.load_producer("round95_retained_stop_producer")
        helper = __import__(
            "test_round29_improvement_loop_red"
        ).Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round95-retained-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            before = helper.start(paths)
            eval_root = paths["repo"] / "eval-root"
            eval_root.mkdir()
            p0 = round59.write_review(
                paths["repo"], "p0_zero", before["source_snapshot"]["sha256"]
            )
            p1 = round59.write_review(
                paths["repo"],
                "reproducible_p1_zero",
                before["source_snapshot"]["sha256"],
            )
            basis = producer.materialize_release_basis(
                repo_root=paths["repo"],
                source_files=before["source_files"],
                expected_source=before["source_snapshot"],
                eval_root=eval_root,
                review_paths=(p0, p1),
                destination_parent=paths["repo"] / ".ao-output" / "round95-bases",
            )
            installed = paths["repo"] / ".ao-output" / "fixture-install"
            installed.mkdir()
            (installed / "runtime-manifest.json").write_text(
                "{}\n", encoding="utf-8"
            )
            install = producer.materialize_canonical_install_artifact(
                installed=installed,
                destination_parent=paths["repo"]
                / ".ao-output"
                / "round95-installs",
                source_basis_sha256=basis["sha256"],
            )

            def relative(value: str) -> str:
                return (
                    Path(value)
                    .resolve()
                    .relative_to(paths["repo"].resolve())
                    .as_posix()
                )

            reference = {
                "schema_version": improvement_loop.SCHEMA_VERSION,
                "sha256": basis["sha256"],
                "root_path": relative(basis["root"]),
                "index_path": relative(basis["index_path"]),
                "index_sha256": basis["index_sha256"],
                "source_sha256": basis["source_sha256"],
                "canonical_install": {
                    "sha256": install["sha256"],
                    "root_path": relative(install["root"]),
                    "index_path": relative(install["index_path"]),
                    "index_sha256": install["index_sha256"],
                    "built_from": "retained_source_snapshot",
                    "source_basis_sha256": basis["sha256"],
                },
                "trust_boundary": "retained_local_snapshot_not_external_signature",
            }
            stopped = json.loads(json.dumps(before))
            gate = {
                "path": ".ao-output/fixture-gate.json",
                "sha256": "a" * 64,
                "checks": {
                    key: True for key in improvement_loop.REQUIRED_GATE_CHECKS
                },
                "evidence": {},
                "evidence_verified": True,
                "valid": True,
                "all_true": True,
                "code": "GATE_VALID",
                "release_basis": reference,
            }
            stopped["iterations"][-1].update(
                {
                    "finding": None,
                    "red_test": None,
                    "gate_result": gate,
                    "decision": "STOP",
                }
            )
            stopped["status"] = "completed"
            stopped["decision"] = "STOP"
            stopped["release_basis"] = reference
            stopped["observed_source_snapshot"] = before["source_snapshot"]
            (paths["state_dir"] / improvement_loop.STATE_FILE).write_text(
                json.dumps(stopped, indent=2) + "\n", encoding="utf-8"
            )
            missing = paths["repo"] / before["source_files"][0]
            os.unlink(missing)

            with mock.patch.object(
                improvement_loop,
                "validate_persisted_gate_evidence",
                return_value=None,
            ):
                recovered = self._resume(paths)
            self.assertEqual("completed", recovered["status"])
            self.assertEqual("STOP", recovered["decision"])
            self.assertEqual(reference, recovered["release_basis"])
            persisted = self._state(paths)
            self.assertEqual(recovered, persisted)
            for label, relative in (
                ("workflow", stopped["workflow"]["path"]),
                ("source-manifest", stopped["source_manifest"]["path"]),
            ):
                with self.subTest(missing_live_governance=label):
                    os.unlink(paths["repo"] / relative)
                    with mock.patch.object(
                        improvement_loop,
                        "validate_persisted_gate_evidence",
                        return_value=None,
                    ):
                        repeated = self._resume(paths)
                    self.assertEqual("completed", repeated["status"])
                    self.assertEqual("STOP", repeated["decision"])
                    self.assertEqual(reference, repeated["release_basis"])
                    self.assertEqual(repeated, self._state(paths))

    def test_retained_graph_step_replay_reads_red_from_frozen_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round95-frozen-red-") as temp_dir:
            native = round94.Round94GraphNativeSourceEpochRedTests()
            graph, helper, paths, state, finding = native._open_graph_finding(
                Path(temp_dir)
            )
            state, _ = native._authorize_v2_epoch(
                graph, paths, state, finding["finding_id"]
            )
            state = native._record_fix(
                graph, helper, paths, state, finding["finding_id"]
            )
            retained_source = paths["repo"] / ".ao-output" / "retained-source"
            for relative in state["source_files"]:
                destination = retained_source / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(paths["repo"] / relative, destination)
            os.unlink(paths["red_test"])

            with self.assertRaises(improvement_loop.LoopError) as raised:
                improvement_loop.validate_persisted_step_evidence(
                    Path(state["repo_root"]), state
                )
            self.assertEqual("STATE_EVIDENCE_INVALID", raised.exception.code)
            improvement_loop.validate_persisted_step_evidence(
                Path(state["repo_root"]),
                state,
                frozen_source_root=retained_source.resolve(),
            )

    def test_independent_recheck_cannot_leave_a_current_round_finding_open(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round95-recheck-") as temp_dir:
            native = round94.Round94GraphNativeSourceEpochRedTests()
            graph, helper, paths, state, finding = native._open_graph_finding(
                Path(temp_dir)
            )
            state, _ = native._authorize_v2_epoch(
                graph, paths, state, finding["finding_id"]
            )
            state = native._record_fix(
                graph, helper, paths, state, finding["finding_id"]
            )
            state = round87.Round87FindingClosureLedgerRedTests().record_plain(
                graph, paths, state, "deterministic_gate"
            )
            accepted = {
                entry["step_id"]: entry["receipt"]["sha256"]
                for entry in state["iterations"][-1]["step_ledger"]
            }
            receipt, _ = graph.write_receipt(
                paths,
                state,
                "independent_recheck",
                dependency_receipts={
                    "deterministic_gate": accepted["deterministic_gate"]
                },
            )

            with self.assertRaises(improvement_loop.LoopError) as raised:
                graph.record(paths, "independent_recheck", receipt)
            self.assertEqual("OPEN_FINDINGS_REMAIN", raised.exception.code)
            unchanged = self._state(paths)
            self.assertEqual(
                "independent_recheck", unchanged["iterations"][-1]["next_step"]
            )
            self.assertEqual(
                "open",
                unchanged["finding_ledger"][finding["finding_id"]]["status"],
            )

    def test_review_finding_cannot_claim_the_controller_drift_namespace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round95-reserved-") as temp_dir:
            graph = round86.Round86WorkflowStepLedgerRedTests()
            helper = round87.Round87FindingClosureLedgerRedTests()
            paths, state = graph.make_graph_candidate(Path(temp_dir))
            state = helper.record_plain(graph, paths, state, "preflight_snapshot")
            accepted = {
                entry["step_id"]: entry["receipt"]["sha256"]
                for entry in state["iterations"][-1]["step_ledger"]
            }
            receipt_path, _ = graph.write_receipt(
                paths,
                state,
                "adversarial_review",
                dependency_receipts={
                    "preflight_snapshot": accepted["preflight_snapshot"]
                },
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["finding_events"] = [
                {
                    "action": "open",
                    "finding_id": "SOURCE-DRIFT-R001",
                    "severity": "P1",
                    "summary": "Attempt to occupy a controller-owned identifier.",
                    "reproducer": "Open a review finding with the reserved ID.",
                    "actual": "The caller controls the finding ID.",
                    "expected": "Controller drift IDs remain reserved.",
                }
            ]
            graph.sync_phase_payload(paths, receipt)
            receipt_path.write_text(
                json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
            )

            with self.assertRaises(improvement_loop.LoopError) as raised:
                graph.record(paths, "adversarial_review", receipt_path)
            self.assertEqual("FINDING_EVENT_INVALID", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
