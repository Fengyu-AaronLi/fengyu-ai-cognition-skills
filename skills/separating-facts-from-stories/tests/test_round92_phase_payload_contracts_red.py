from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import improvement_loop  # noqa: E402
import test_round86_workflow_step_ledger_red as round86  # noqa: E402


class Round92PhasePayloadContractsRedTests(unittest.TestCase):
    """An ordered receipt must prove its phase, not merely cite any JSON file."""

    def test_generic_observed_json_cannot_prove_preflight(self) -> None:
        helper = round86.Round86WorkflowStepLedgerRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round92-placeholder-") as temp_dir:
            paths, state = helper.make_graph_candidate(Path(temp_dir))
            receipt_path, artifact_path = helper.write_receipt(
                paths, state, "preflight_snapshot"
            )
            helper.begin_and_bind(paths, "preflight_snapshot", receipt_path)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            artifact_path.write_text(
                '{"step_id":"preflight_snapshot","observed":true}\n',
                encoding="utf-8",
            )
            receipt["artifacts"][0] = {
                "role": "step_evidence",
                "path": artifact_path.relative_to(paths["repo"]).as_posix(),
                "sha256": round86.sha256(artifact_path),
            }
            receipt_path.write_text(
                json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
            )

            with self.assertRaises(improvement_loop.LoopError) as raised:
                improvement_loop.command_record_step(
                    argparse.Namespace(
                        state_dir=str(paths["state_dir"]),
                        step_id="preflight_snapshot",
                        receipt=receipt_path.relative_to(paths["repo"]).as_posix(),
                    )
                )
            self.assertEqual("PHASE_PAYLOAD_INVALID", raised.exception.code)

    def test_cross_phase_payload_type_is_rejected(self) -> None:
        helper = round86.Round86WorkflowStepLedgerRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round92-cross-") as temp_dir:
            paths, state = helper.make_graph_candidate(Path(temp_dir))
            receipt_path, artifact_path = helper.write_receipt(
                paths, state, "preflight_snapshot"
            )
            helper.begin_and_bind(paths, "preflight_snapshot", receipt_path)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            artifact_path.write_text(
                json.dumps(
                    {
                        "schema_version": improvement_loop.SCHEMA_VERSION,
                        "evidence_type": "eval_audit.v1",
                        "controller_run_id": state["controller_run_id"],
                        "iteration_id": state["iterations"][-1]["iteration_id"],
                        "source_sha256": state["source_snapshot"]["sha256"],
                        "result": {
                            "valid": True,
                            "case_count": 18,
                            "artifact_count": 16,
                            "missing": [],
                            "suite_errors": [],
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            receipt["artifacts"][0]["sha256"] = round86.sha256(artifact_path)
            receipt_path.write_text(
                json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
            )

            with self.assertRaises(improvement_loop.LoopError) as raised:
                improvement_loop.command_record_step(
                    argparse.Namespace(
                        state_dir=str(paths["state_dir"]),
                        step_id="preflight_snapshot",
                        receipt=receipt_path.relative_to(paths["repo"]).as_posix(),
                    )
                )
            self.assertEqual("PHASE_PAYLOAD_INVALID", raised.exception.code)

    def test_all_nine_external_phases_reject_the_generic_placeholder(self) -> None:
        helper = round86.Round86WorkflowStepLedgerRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round92-matrix-") as temp_dir:
            root = Path(temp_dir)
            for target_index, target_step in enumerate(
                improvement_loop.EXTERNAL_EXECUTION_STEPS
            ):
                with self.subTest(step_id=target_step):
                    paths, state = helper.make_graph_candidate(
                        root / f"candidate-{target_index:02d}"
                    )
                    for step_id in improvement_loop.EXTERNAL_EXECUTION_STEPS[
                        :target_index
                    ]:
                        dependencies = dict(
                            improvement_loop.REQUIRED_EXECUTION_GRAPH
                        )[step_id]
                        accepted = {
                            item["step_id"]: item["receipt"]["sha256"]
                            for item in state["iterations"][-1]["step_ledger"]
                        }
                        receipt, _ = helper.write_receipt(
                            paths,
                            state,
                            step_id,
                            dependency_receipts={
                                dependency: accepted[dependency]
                                for dependency in dependencies
                            },
                        )
                        state = helper.record(paths, step_id, receipt)

                    dependencies = dict(improvement_loop.REQUIRED_EXECUTION_GRAPH)[
                        target_step
                    ]
                    accepted = {
                        item["step_id"]: item["receipt"]["sha256"]
                        for item in state["iterations"][-1]["step_ledger"]
                    }
                    receipt_path, artifact_path = helper.write_receipt(
                        paths,
                        state,
                        target_step,
                        dependency_receipts={
                            dependency: accepted[dependency]
                            for dependency in dependencies
                        },
                    )
                    helper.begin_and_bind(paths, target_step, receipt_path)
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                    artifact_path.write_text(
                        json.dumps({"step_id": target_step, "observed": True})
                        + "\n",
                        encoding="utf-8",
                    )
                    receipt["artifacts"][0] = {
                        "role": "step_evidence",
                        "path": artifact_path.relative_to(paths["repo"]).as_posix(),
                        "sha256": round86.sha256(artifact_path),
                    }
                    receipt_path.write_text(
                        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
                    )
                    with self.assertRaises(improvement_loop.LoopError) as raised:
                        improvement_loop.command_record_step(
                            argparse.Namespace(
                                state_dir=str(paths["state_dir"]),
                                step_id=target_step,
                                receipt=receipt_path.relative_to(
                                    paths["repo"]
                                ).as_posix(),
                            )
                        )
                    self.assertEqual(
                        "PHASE_PAYLOAD_INVALID", raised.exception.code
                    )

    def test_unhashable_identity_values_fail_closed_as_structured_errors(self) -> None:
        helper = round86.Round86WorkflowStepLedgerRedTests()
        mutations = {
            "adversarial_review": ("reviewer_ids", [{}, {}]),
            "isolated_eval": ("runner_ids", [{} for _ in range(18)]),
        }
        with tempfile.TemporaryDirectory(prefix="sffs-round92-unhashable-") as temp_dir:
            root = Path(temp_dir)
            for target_index, (target_step, (field, malformed)) in enumerate(
                mutations.items()
            ):
                with self.subTest(step_id=target_step):
                    paths, state = helper.make_graph_candidate(
                        root / f"candidate-{target_index:02d}"
                    )
                    target_position = improvement_loop.EXTERNAL_EXECUTION_STEPS.index(
                        target_step
                    )
                    for step_id in improvement_loop.EXTERNAL_EXECUTION_STEPS[
                        :target_position
                    ]:
                        dependencies = dict(
                            improvement_loop.REQUIRED_EXECUTION_GRAPH
                        )[step_id]
                        accepted = {
                            item["step_id"]: item["receipt"]["sha256"]
                            for item in state["iterations"][-1]["step_ledger"]
                        }
                        receipt, _ = helper.write_receipt(
                            paths,
                            state,
                            step_id,
                            dependency_receipts={
                                dependency: accepted[dependency]
                                for dependency in dependencies
                            },
                        )
                        state = helper.record(paths, step_id, receipt)

                    dependencies = dict(improvement_loop.REQUIRED_EXECUTION_GRAPH)[
                        target_step
                    ]
                    accepted = {
                        item["step_id"]: item["receipt"]["sha256"]
                        for item in state["iterations"][-1]["step_ledger"]
                    }
                    receipt_path, artifact_path = helper.write_receipt(
                        paths,
                        state,
                        target_step,
                        dependency_receipts={
                            dependency: accepted[dependency]
                            for dependency in dependencies
                        },
                    )
                    helper.begin_and_bind(paths, target_step, receipt_path)
                    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                    payload["result"][field] = malformed
                    artifact_path.write_text(
                        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
                    )
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                    receipt["artifacts"][0]["sha256"] = round86.sha256(artifact_path)
                    receipt_path.write_text(
                        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
                    )
                    with self.assertRaises(improvement_loop.LoopError) as raised:
                        improvement_loop.command_record_step(
                            argparse.Namespace(
                                state_dir=str(paths["state_dir"]),
                                step_id=target_step,
                                receipt=receipt_path.relative_to(
                                    paths["repo"]
                                ).as_posix(),
                            )
                        )
                    self.assertEqual(
                        "PHASE_PAYLOAD_INVALID", raised.exception.code
                    )


if __name__ == "__main__":
    unittest.main()
