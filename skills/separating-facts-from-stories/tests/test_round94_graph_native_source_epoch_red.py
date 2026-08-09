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
import test_round87_finding_closure_ledger_red as round87  # noqa: E402


class Round94GraphNativeSourceEpochRedTests(unittest.TestCase):
    """A graph-native finding must be able to create RED before implementation."""

    def _open_graph_finding(self, root: Path):
        graph = round86.Round86WorkflowStepLedgerRedTests()
        helper = round87.Round87FindingClosureLedgerRedTests()
        paths, state = graph.make_graph_candidate(root)
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
        finding = {
            "finding_id": "P1-GRAPH-NATIVE-RED",
            "severity": "P1",
            "summary": "A newly reviewed graph finding needs a new RED test.",
            "reproducer": "Open the finding in adversarial_review.",
            "actual": "The finding has no pre-existing red_test binding.",
            "expected": "The source epoch authors RED before implementation.",
        }
        receipt["finding_events"] = [{"action": "open", **finding}]
        graph.sync_phase_payload(paths, receipt)
        receipt_path.write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
        state = graph.record(paths, "adversarial_review", receipt_path)
        self.assertIsNone(state["finding_ledger"][finding["finding_id"]]["red_test"])
        return graph, helper, paths, state, finding

    def _authorize_v2_epoch(
        self,
        graph,
        paths,
        state: dict,
        finding_id: str,
        *,
        mutate_red_after: bool = False,
        implementation_file: Path | None = None,
    ):
        with redirect_stdout(StringIO()):
            improvement_loop.command_begin_step(
                argparse.Namespace(
                    state_dir=str(paths["state_dir"]),
                    step_id="red_green_fix",
                )
            )
        state = json.loads(
            (paths["state_dir"] / improvement_loop.STATE_FILE).read_text(
                encoding="utf-8"
            )
        )
        iteration = state["iterations"][-1]
        active = iteration["active_work_order"]
        before_files = dict(state["source_snapshot"]["files"])

        red_path = paths["red_test"].relative_to(paths["repo"]).as_posix()
        red_before_blob = (
            paths["state_dir"] / f"{active['attempt_id']}-before-test.py"
        )
        red_before_blob.write_bytes(paths["red_test"].read_bytes())
        red_content = (
            paths["red_test"].read_text(encoding="utf-8")
            + "\ndef test_graph_native_red():\n"
            + "    from pathlib import Path\n"
            + "    skill = Path(__file__).resolve().parents[1] / 'SKILL.md'\n"
            + "    assert '# graph-native fix ' in skill.read_text(encoding='utf-8')\n"
        )
        red_blob = paths["state_dir"] / f"{active['attempt_id']}-red-test.py"
        red_blob.write_text(red_content, encoding="utf-8")
        red_files = dict(before_files)
        red_files[red_path] = round86.sha256(red_blob)

        implementation_file = implementation_file or paths["skill_file"]
        implementation_path = implementation_file.relative_to(
            paths["repo"]
        ).as_posix()
        implementation_red_blob = (
            paths["state_dir"] / f"{active['attempt_id']}-red-implementation"
        )
        implementation_red_blob.write_bytes(implementation_file.read_bytes())
        after_content = (
            implementation_file.read_text(encoding="utf-8")
            + f"\n# graph-native fix {active['attempt_id']}\n"
        )
        after_blob = paths["state_dir"] / f"{active['attempt_id']}-after-SKILL.md"
        after_blob.write_text(after_content, encoding="utf-8")
        after_files = dict(red_files)
        after_files[implementation_path] = round86.sha256(after_blob)

        if mutate_red_after:
            after_files[red_path] = "f" * 64

        plan = {
            "schema_version": improvement_loop.SCHEMA_VERSION,
            "plan_type": "source_epoch_plan.v2",
            "controller_run_id": state["controller_run_id"],
            "iteration_id": iteration["iteration_id"],
            "attempt_id": active["attempt_id"],
            "source_before_sha256": improvement_loop.canonical_sha256(
                before_files
            ),
            "red_source_sha256": improvement_loop.canonical_sha256(red_files),
            "source_after_sha256": improvement_loop.canonical_sha256(after_files),
            "source_before_files": dict(sorted(before_files.items())),
            "red_source_files": dict(sorted(red_files.items())),
            "source_after_files": dict(sorted(after_files.items())),
            "finding_red_tests": [
                {
                    "finding_id": finding_id,
                    "path": red_path,
                    "sha256": round86.sha256(red_blob),
                }
            ],
            "red_changes": [
                {
                    "path": red_path,
                    "before_blob": {
                        "path": red_before_blob.relative_to(
                            paths["repo"]
                        ).as_posix(),
                        "sha256": round86.sha256(red_before_blob),
                    },
                    "red_blob": {
                        "path": red_blob.relative_to(paths["repo"]).as_posix(),
                        "sha256": round86.sha256(red_blob),
                    },
                }
            ],
            "implementation_changes": [
                {
                    "path": implementation_path,
                    "red_blob": {
                        "path": implementation_red_blob.relative_to(
                            paths["repo"]
                        ).as_posix(),
                        "sha256": round86.sha256(implementation_red_blob),
                    },
                    "after_blob": {
                        "path": after_blob.relative_to(paths["repo"]).as_posix(),
                        "sha256": round86.sha256(after_blob),
                    },
                }
            ],
        }
        plan_path = paths["state_dir"] / f"{active['attempt_id']}-epoch-v2.json"
        plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        with redirect_stdout(StringIO()):
            improvement_loop.command_authorize_fix(
                argparse.Namespace(
                    state_dir=str(paths["state_dir"]),
                    plan=plan_path.relative_to(paths["repo"]).as_posix(),
                )
            )
        paths["red_test"].write_text(red_content, encoding="utf-8")
        implementation_file.write_text(after_content, encoding="utf-8")
        state = json.loads(
            (paths["state_dir"] / improvement_loop.STATE_FILE).read_text(
                encoding="utf-8"
            )
        )
        return state, plan

    def _record_fix(
        self,
        graph,
        helper,
        paths,
        state: dict,
        finding_id: str,
        *,
        wrong_red_source: bool = False,
    ):
        accepted = {
            entry["step_id"]: entry["receipt"]["sha256"]
            for entry in state["iterations"][-1]["step_ledger"]
        }
        receipt_path, _ = graph.write_receipt(
            paths,
            state,
            "red_green_fix",
            dependency_receipts={
                "adversarial_review": accepted["adversarial_review"]
            },
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        epoch = state["iterations"][-1]["pending_source_epoch"]
        red_test = {
            "path": epoch["finding_red_tests"][0]["path"],
            "sha256": epoch["finding_red_tests"][0]["sha256"],
        }
        receipt["artifacts"].append({"role": "red_test", **red_test})
        red_run = helper.add_command_artifact(
            paths,
            state,
            receipt,
            "round94-red-run.json",
            role="red_run",
            finding_id=finding_id,
            red_test=red_test,
            execution_id="round94-red-execution",
            causal_parent={
                "kind": "finding_opening",
                "sha256": state["finding_ledger"][finding_id]["opened_by"][
                    "evidence_sha256"
                ],
            },
            exit_code=1,
            failures=1,
            classification="expected_failure_reproduced",
        )
        if wrong_red_source:
            red_run_path = paths["repo"] / red_run["path"]
            red_run_document = json.loads(
                red_run_path.read_text(encoding="utf-8")
            )
            red_run_document["source_sha256"] = epoch["source_before_sha256"]
            red_run_path.write_text(
                json.dumps(red_run_document, indent=2) + "\n", encoding="utf-8"
            )
            red_run["sha256"] = round86.sha256(red_run_path)
        green_run = helper.add_command_artifact(
            paths,
            state,
            receipt,
            "round94-green-run.json",
            role="green_run",
            finding_id=finding_id,
            red_test=red_test,
            execution_id="round94-green-execution",
            causal_parent={"kind": "red_run", "sha256": red_run["sha256"]},
            exit_code=0,
            failures=0,
            classification="passed",
        )
        receipt["finding_events"] = [
            {
                "action": "fix_claimed",
                "finding_id": finding_id,
                "red_test": red_test,
                "red_run": {
                    "path": red_run["path"],
                    "sha256": red_run["sha256"],
                },
                "green_run": {
                    "path": green_run["path"],
                    "sha256": green_run["sha256"],
                },
            }
        ]
        graph.sync_phase_payload(paths, receipt)
        receipt_path.write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
        return graph.record(paths, "red_green_fix", receipt_path)

    def test_graph_finding_can_author_red_then_fix_without_restart(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round94-native-") as temp_dir:
            graph, helper, paths, state, finding = self._open_graph_finding(
                Path(temp_dir)
            )
            state, _ = self._authorize_v2_epoch(
                graph, paths, state, finding["finding_id"]
            )
            updated = self._record_fix(
                graph, helper, paths, state, finding["finding_id"]
            )
            epoch = updated["iterations"][-1]["source_epoch"]
            self.assertNotEqual(
                epoch["source_before_sha256"], epoch["red_source_sha256"]
            )
            self.assertNotEqual(
                epoch["red_source_sha256"], epoch["source_after_sha256"]
            )
            self.assertEqual(
                epoch["finding_red_tests"][0]["sha256"],
                updated["finding_ledger"][finding["finding_id"]]["red_test"][
                    "sha256"
                ],
            )

    def test_red_test_must_be_byte_identical_between_red_and_green(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round94-freeze-") as temp_dir:
            graph, _, paths, state, finding = self._open_graph_finding(Path(temp_dir))
            with self.assertRaises(improvement_loop.LoopError) as raised:
                self._authorize_v2_epoch(
                    graph,
                    paths,
                    state,
                    finding["finding_id"],
                    mutate_red_after=True,
                )
            self.assertEqual("SOURCE_EPOCH_PLAN_INVALID", raised.exception.code)

    def test_v2_epoch_retains_red_and_after_blobs_for_replay(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round94-retain-") as temp_dir:
            graph, _, paths, state, finding = self._open_graph_finding(Path(temp_dir))
            state, _ = self._authorize_v2_epoch(
                graph, paths, state, finding["finding_id"]
            )
            pending = state["iterations"][-1]["pending_source_epoch"]
            before_blob = (
                paths["repo"]
                / pending["red_changes"][0]["before_blob"]["path"]
            )
            red_blob = paths["repo"] / pending["red_changes"][0]["red_blob"]["path"]
            implementation_red_blob = (
                paths["repo"]
                / pending["implementation_changes"][0]["red_blob"]["path"]
            )
            after_blob = (
                paths["repo"]
                / pending["implementation_changes"][0]["after_blob"]["path"]
            )
            self.assertTrue(before_blob.is_file())
            self.assertTrue(red_blob.is_file())
            self.assertTrue(implementation_red_blob.is_file())
            self.assertTrue(after_blob.is_file())
            self.assertEqual(
                pending["red_changes"][0]["before_blob"]["sha256"],
                round86.sha256(before_blob),
            )
            self.assertEqual(
                pending["red_changes"][0]["red_blob"]["sha256"],
                round86.sha256(red_blob),
            )
            self.assertEqual(
                pending["implementation_changes"][0]["red_blob"]["sha256"],
                round86.sha256(implementation_red_blob),
            )
            self.assertEqual(
                pending["implementation_changes"][0]["after_blob"]["sha256"],
                round86.sha256(after_blob),
            )

    def test_red_run_must_bind_the_intermediate_red_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round94-red-source-") as temp_dir:
            graph, helper, paths, state, finding = self._open_graph_finding(
                Path(temp_dir)
            )
            state, _ = self._authorize_v2_epoch(
                graph, paths, state, finding["finding_id"]
            )
            with self.assertRaises(improvement_loop.LoopError) as raised:
                self._record_fix(
                    graph,
                    helper,
                    paths,
                    state,
                    finding["finding_id"],
                    wrong_red_source=True,
                )
            self.assertEqual("FINDING_CLOSURE_INVALID", raised.exception.code)

    def test_source_epoch_cannot_modify_the_controller(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round94-control-") as temp_dir:
            graph, _, paths, state, finding = self._open_graph_finding(Path(temp_dir))
            with self.assertRaises(improvement_loop.LoopError) as raised:
                self._authorize_v2_epoch(
                    graph,
                    paths,
                    state,
                    finding["finding_id"],
                    implementation_file=paths["controller"],
                )
            self.assertEqual("SOURCE_EPOCH_PLAN_INVALID", raised.exception.code)

    def test_any_retained_epoch_blob_tamper_invalidates_state(self) -> None:
        for label, selector in (
            (
                "before",
                lambda pending: pending["red_changes"][0]["before_blob"]["path"],
            ),
            (
                "red-test",
                lambda pending: pending["red_changes"][0]["red_blob"]["path"],
            ),
            (
                "red-implementation",
                lambda pending: pending["implementation_changes"][0]["red_blob"][
                    "path"
                ],
            ),
            (
                "after",
                lambda pending: pending["implementation_changes"][0]["after_blob"][
                    "path"
                ],
            ),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory(
                prefix=f"sffs-round94-tamper-{label}-"
            ) as temp_dir:
                graph, _, paths, state, finding = self._open_graph_finding(
                    Path(temp_dir)
                )
                state, _ = self._authorize_v2_epoch(
                    graph, paths, state, finding["finding_id"]
                )
                pending = state["iterations"][-1]["pending_source_epoch"]
                blob = paths["repo"] / selector(pending)
                blob.write_bytes(blob.read_bytes() + b"tampered\n")
                with self.assertRaises(improvement_loop.LoopError) as raised:
                    improvement_loop.load_state(paths["state_dir"])
                self.assertEqual("STATE_EVIDENCE_INVALID", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
