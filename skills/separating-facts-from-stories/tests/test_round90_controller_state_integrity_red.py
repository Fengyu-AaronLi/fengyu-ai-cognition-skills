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


class Round90ControllerStateIntegrityRedTests(unittest.TestCase):
    """The controller must derive state from evidence, not trust self-reports."""

    def setUp(self) -> None:
        self.helper = round87.Round87FindingClosureLedgerRedTests()

    @staticmethod
    def _write_receipt(path: Path, receipt: dict) -> None:
        path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    def _record_through_review(self, graph, paths, state):
        state = self.helper.record_plain(
            graph, paths, state, "preflight_snapshot"
        )
        return self.helper.record_plain(
            graph, paths, state, "adversarial_review"
        )

    def _write_fix_receipt(
        self,
        graph,
        paths,
        state,
        finding_id: str,
        *,
        red_content: str = '{"exit_code":1}\n',
        green_content: str = '{"exit_code":0}\n',
    ) -> Path:
        if not isinstance(
            state["iterations"][-1].get("pending_source_epoch"), dict
        ):
            state = self.helper.authorize_fixture_fix(graph, paths, state)
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
        red_run = self.helper.add_artifact(
            paths, receipt, "round90-red-run.json", red_content, "red_run"
        )
        green_run = self.helper.add_artifact(
            paths, receipt, "round90-green-run.json", green_content, "green_run"
        )
        red_test = {
            "role": "red_test",
            "path": "skills/separating-facts-from-stories/tests/test_probe.py",
            "sha256": round87.round86.sha256(paths["red_test"]),
        }
        receipt["artifacts"].append(red_test)
        receipt["finding_events"] = [
            {
                "action": "fix_claimed",
                "finding_id": finding_id,
                "red_test": {
                    key: red_test[key] for key in ("path", "sha256")
                },
                "red_run": {
                    "path": red_run["path"],
                    "sha256": red_run["sha256"],
                    "exit_code": 1,
                },
                "green_run": {
                    "path": green_run["path"],
                    "sha256": green_run["sha256"],
                    "exit_code": 0,
                },
            }
        ]
        graph.sync_phase_payload(paths, receipt)
        self._write_receipt(receipt_path, receipt)
        return receipt_path

    def _write_recheck_receipt(
        self,
        graph,
        paths,
        state,
        finding_id: str,
        *,
        content: str = '{"exit_code":0,"result":"not_reproduced"}\n',
    ) -> Path:
        accepted = {
            entry["step_id"]: entry["receipt"]["sha256"]
            for entry in state["iterations"][-1]["step_ledger"]
        }
        receipt_path, _ = graph.write_receipt(
            paths,
            state,
            "independent_recheck",
            dependency_receipts={
                "deterministic_gate": accepted["deterministic_gate"]
            },
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        recheck = self.helper.add_artifact(
            paths,
            receipt,
            "round90-independent-recheck.json",
            content,
            "independent_recheck",
        )
        receipt["finding_events"] = [
            {
                "action": "close",
                "finding_id": finding_id,
                "disposition": "not_reproduced",
                "recheck": {
                    "path": recheck["path"],
                    "sha256": recheck["sha256"],
                    "exit_code": 0,
                },
            }
        ]
        graph.sync_phase_payload(paths, receipt)
        self._write_receipt(receipt_path, receipt)
        return receipt_path

    def _write_typed_fix_receipt(
        self, graph, paths, state, finding_id: str
    ) -> Path:
        if not isinstance(
            state["iterations"][-1].get("pending_source_epoch"), dict
        ):
            state = self.helper.authorize_fixture_fix(graph, paths, state)
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
        red_test = {
            "path": "skills/separating-facts-from-stories/tests/test_probe.py",
            "sha256": round87.round86.sha256(paths["red_test"]),
        }
        receipt["artifacts"].append({"role": "red_test", **red_test})
        opening_sha256 = state["finding_ledger"][finding_id]["opened_by"][
            "evidence_sha256"
        ]
        red_run = self.helper.add_command_artifact(
            paths,
            state,
            receipt,
            "round90-typed-red.json",
            role="red_run",
            finding_id=finding_id,
            red_test=red_test,
            execution_id="round90-red-command",
            causal_parent={
                "kind": "finding_opening",
                "sha256": opening_sha256,
            },
            exit_code=1,
            failures=1,
            classification="expected_failure_reproduced",
        )
        green_run = self.helper.add_command_artifact(
            paths,
            state,
            receipt,
            "round90-typed-green.json",
            role="green_run",
            finding_id=finding_id,
            red_test=red_test,
            execution_id="round90-green-command",
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
        self._write_receipt(receipt_path, receipt)
        return receipt_path

    def _write_typed_recheck_receipt(
        self,
        graph,
        paths,
        state,
        finding_id: str,
        *,
        exit_code: int = 0,
        failures: int = 0,
        classification: str = "not_reproduced",
    ) -> Path:
        accepted = {
            entry["step_id"]: entry["receipt"]["sha256"]
            for entry in state["iterations"][-1]["step_ledger"]
        }
        receipt_path, _ = graph.write_receipt(
            paths,
            state,
            "independent_recheck",
            dependency_receipts={
                "deterministic_gate": accepted["deterministic_gate"]
            },
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        recheck = self.helper.add_command_artifact(
            paths,
            state,
            receipt,
            "round90-typed-recheck.json",
            role="independent_recheck",
            finding_id=finding_id,
            red_test=state["finding_ledger"][finding_id]["red_test"],
            execution_id="round90-recheck-command",
            causal_parent={
                "kind": "fix_event",
                "sha256": state["finding_ledger"][finding_id]["fix"][
                    "event_sha256"
                ],
            },
            exit_code=exit_code,
            failures=failures,
            classification=classification,
        )
        receipt["finding_events"] = [
            {
                "action": "close",
                "finding_id": finding_id,
                "disposition": "not_reproduced",
                "recheck": {
                    "path": recheck["path"],
                    "sha256": recheck["sha256"],
                },
            }
        ]
        graph.sync_phase_payload(paths, receipt)
        self._write_receipt(receipt_path, receipt)
        return receipt_path

    def test_deleted_finding_cannot_disappear_from_replayed_history(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round90-ledger-") as temp_dir:
            _, paths, state, finding = self.helper.open_finding(Path(temp_dir))
            state_path = paths["state_dir"] / improvement_loop.STATE_FILE
            state["finding_ledger"].pop(finding["finding_id"])
            state["iterations"][-1]["carried_findings"].remove(
                finding["finding_id"]
            )
            self._write_receipt(state_path, state)

            with self.assertRaises(improvement_loop.LoopError) as raised:
                improvement_loop.load_state(paths["state_dir"])
            self.assertEqual("STATE_EVIDENCE_INVALID", raised.exception.code)

    def test_event_exit_codes_cannot_override_command_receipt_contents(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round90-command-") as temp_dir:
            graph, paths, state, finding = self.helper.open_finding(Path(temp_dir))
            state = self._record_through_review(graph, paths, state)
            receipt_path = self._write_fix_receipt(
                graph,
                paths,
                state,
                finding["finding_id"],
                red_content='{"exit_code":0}\n',
                green_content='{"exit_code":1}\n',
            )

            with self.assertRaises(improvement_loop.LoopError) as raised:
                graph.record(paths, "red_green_fix", receipt_path)
            self.assertEqual("FINDING_CLOSURE_INVALID", raised.exception.code)

    def test_recheck_event_cannot_override_a_failing_command_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round90-recheck-") as temp_dir:
            graph, paths, state, finding = self.helper.open_finding(Path(temp_dir))
            state = self._record_through_review(graph, paths, state)
            fix_path = self._write_typed_fix_receipt(
                graph, paths, state, finding["finding_id"]
            )
            state = graph.record(paths, "red_green_fix", fix_path)
            state = self.helper.record_plain(
                graph, paths, state, "deterministic_gate"
            )
            recheck_path = self._write_typed_recheck_receipt(
                graph,
                paths,
                state,
                finding["finding_id"],
                exit_code=1,
                failures=1,
                classification="still_reproduced",
            )

            with self.assertRaises(improvement_loop.LoopError) as raised:
                graph.record(paths, "independent_recheck", recheck_path)
            self.assertEqual("FINDING_CLOSURE_INVALID", raised.exception.code)

    def test_aborted_prepared_closure_is_not_promoted_after_source_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round90-recovery-") as temp_dir:
            graph, paths, state, finding = self.helper.open_finding(Path(temp_dir))
            finding_id = finding["finding_id"]
            state = self._record_through_review(graph, paths, state)
            fix_path = self._write_typed_fix_receipt(
                graph, paths, state, finding_id
            )
            state = graph.record(paths, "red_green_fix", fix_path)
            state = self.helper.record_plain(
                graph, paths, state, "deterministic_gate"
            )
            recheck_path = self._write_typed_recheck_receipt(
                graph, paths, state, finding_id
            )
            graph.begin_and_bind(
                paths, "independent_recheck", recheck_path
            )

            with patch.dict(
                os.environ,
                {"SFFS_IMPROVEMENT_LOOP_FAILPOINT": "after_prepare"},
            ):
                with self.assertRaises(improvement_loop.LoopError) as crashed:
                    graph.record(
                        paths,
                        "independent_recheck",
                        recheck_path,
                        auto_begin=False,
                    )
            self.assertEqual("SIMULATED_CRASH", crashed.exception.code)

            paths["skill_file"].write_text(
                paths["skill_file"].read_text(encoding="utf-8")
                + "\nchanged after an unpublished closure\n",
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

            self.assertEqual("open", recovered["finding_ledger"][finding_id]["status"])
            self.assertIsNone(recovered["finding_ledger"][finding_id]["closure"])
            self.assertIn(
                finding_id, recovered["iterations"][-1]["carried_findings"]
            )
            self.assertTrue(
                list(
                    (paths["state_dir"] / "transactions").glob(
                        "*-aborted.json"
                    )
                )
            )


if __name__ == "__main__":
    unittest.main()
