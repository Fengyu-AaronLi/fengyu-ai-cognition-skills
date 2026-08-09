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
import test_round29_improvement_loop_red as round29  # noqa: E402
import test_round86_workflow_step_ledger_red as round86  # noqa: E402


class Round87FindingClosureLedgerRedTests(unittest.TestCase):
    """A carried finding is data with a closure proof, not a prose reminder."""

    def open_finding(self, root: Path):
        graph = round86.Round86WorkflowStepLedgerRedTests()
        legacy = round29.Round29ImprovementLoopRedTests()
        paths, state = graph.make_graph_candidate(root)
        finding_path, finding = legacy.write_finding(paths)
        gate_path, _ = legacy.write_gate(
            paths, state, overrides={"reproducible_p1_zero": False}
        )
        result = legacy.advance(paths, gate_path, finding=finding_path)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        state = legacy.parsed(result)
        return graph, paths, state, finding

    def record_plain(self, graph, paths, state, step_id):
        accepted = {
            entry["step_id"]: entry["receipt"]["sha256"]
            for entry in state["iterations"][-1]["step_ledger"]
        }
        dependencies = dict(improvement_loop.REQUIRED_EXECUTION_GRAPH)[step_id]
        receipt, _ = graph.write_receipt(
            paths,
            state,
            step_id,
            dependency_receipts={item: accepted[item] for item in dependencies},
        )
        return graph.record(paths, step_id, receipt)

    def add_artifact(self, paths, receipt: dict, name: str, content: str, role: str):
        path = paths["state_dir"] / name
        path.write_text(content, encoding="utf-8")
        descriptor = {
            "role": role,
            "path": path.relative_to(paths["repo"]).as_posix(),
            "sha256": round86.sha256(path),
        }
        receipt["artifacts"].append(descriptor)
        return descriptor

    def add_command_artifact(
        self,
        paths,
        state: dict,
        receipt: dict,
        name: str,
        *,
        role: str,
        finding_id: str,
        red_test: dict[str, str],
        execution_id: str,
        causal_parent: dict[str, str],
        exit_code: int,
        failures: int,
        classification: str,
    ):
        iteration = state["iterations"][-1]
        source_epoch = iteration.get("pending_source_epoch")
        if not isinstance(source_epoch, dict):
            source_epoch = iteration.get("source_epoch")
        if role == "red_run" and isinstance(source_epoch, dict):
            command_source_sha256 = source_epoch["red_source_sha256"]
        elif role == "green_run" and isinstance(source_epoch, dict):
            command_source_sha256 = source_epoch["source_after_sha256"]
        else:
            command_source_sha256 = iteration["active_source_sha256"]
        document = {
            "schema_version": improvement_loop.SCHEMA_VERSION,
            "receipt_type": improvement_loop.COMMAND_EXECUTION_RECEIPT_TYPE,
            "controller_run_id": state["controller_run_id"],
            "iteration_id": state["iterations"][-1]["iteration_id"],
            "source_sha256": command_source_sha256,
            "phase_step_id": receipt["step_id"],
            "phase_execution_id": receipt["producer"]["execution_id"],
            "finding_id": finding_id,
            "role": role,
            "execution_id": execution_id,
            "red_test": red_test,
            "causal_parent": causal_parent,
            "command": {
                "argv": ["python3", red_test["path"]],
                "cwd": str(paths["repo"].resolve()),
                "shell": False,
                "timeout_seconds": 600,
            },
            "result": {
                "ran": True,
                "timed_out": False,
                "exit_code": exit_code,
                "tests_run": 1,
                "failures": failures,
                "errors": 0,
                "skipped": 0,
                "classification": classification,
            },
            "producer": {
                "actor_id": receipt["producer"]["actor_id"],
                "trust_boundary": improvement_loop.COMMAND_EXECUTION_TRUST_BOUNDARY,
            },
        }
        return self.add_artifact(
            paths,
            receipt,
            name,
            json.dumps(document, indent=2) + "\n",
            role,
        )

    def authorize_fixture_fix(self, graph, paths, state: dict) -> dict:
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
        implementation_path = paths["skill_file"].relative_to(paths["repo"]).as_posix()
        after_content = (
            paths["skill_file"].read_text(encoding="utf-8")
            + f"\n# authorized fix {active['attempt_id']}\n"
        )
        after_blob = paths["state_dir"] / f"{active['attempt_id']}-after-SKILL.md"
        after_blob.write_text(after_content, encoding="utf-8")
        implementation_red_blob = (
            paths["state_dir"] / f"{active['attempt_id']}-red-SKILL.md"
        )
        implementation_red_blob.write_bytes(paths["skill_file"].read_bytes())
        after_files = dict(before_files)
        after_files[implementation_path] = round86.sha256(after_blob)
        open_ids = sorted(
            finding_id
            for finding_id, item in state["finding_ledger"].items()
            if item["status"] == "open"
        )
        red_tests = []
        for finding_id in open_ids:
            red_test = state["finding_ledger"][finding_id]["red_test"]
            if red_test not in red_tests:
                red_tests.append(dict(red_test))
        red_tests.sort(key=lambda item: (item["path"], item["sha256"]))
        finding_red_tests = [
            {
                "finding_id": finding_id,
                "path": state["finding_ledger"][finding_id]["red_test"]["path"],
                "sha256": state["finding_ledger"][finding_id]["red_test"]["sha256"],
            }
            for finding_id in open_ids
        ]
        plan = {
            "schema_version": improvement_loop.SCHEMA_VERSION,
            "plan_type": improvement_loop.SOURCE_EPOCH_PLAN_TYPE,
            "controller_run_id": state["controller_run_id"],
            "iteration_id": iteration["iteration_id"],
            "attempt_id": active["attempt_id"],
            "source_before_sha256": improvement_loop.canonical_sha256(before_files),
            "red_source_sha256": improvement_loop.canonical_sha256(before_files),
            "source_after_sha256": improvement_loop.canonical_sha256(after_files),
            "source_before_files": dict(sorted(before_files.items())),
            "red_source_files": dict(sorted(before_files.items())),
            "source_after_files": dict(sorted(after_files.items())),
            "finding_red_tests": finding_red_tests,
            "red_changes": [],
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
        plan_path = paths["state_dir"] / f"{active['attempt_id']}-source-epoch.json"
        plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        with redirect_stdout(StringIO()):
            improvement_loop.command_authorize_fix(
                argparse.Namespace(
                    state_dir=str(paths["state_dir"]),
                    plan=plan_path.relative_to(paths["repo"]).as_posix(),
                )
            )
        paths["skill_file"].write_text(after_content, encoding="utf-8")
        return json.loads(
            (paths["state_dir"] / improvement_loop.STATE_FILE).read_text(
                encoding="utf-8"
            )
        )

    def record_typed_fix(self, graph, paths, state: dict, finding_id: str) -> dict:
        if not isinstance(
            state["iterations"][-1].get("pending_source_epoch"), dict
        ):
            state = self.authorize_fixture_fix(graph, paths, state)
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
            "sha256": round86.sha256(paths["red_test"]),
        }
        receipt["artifacts"].append({"role": "red_test", **red_test})
        opening_sha256 = state["finding_ledger"][finding_id]["opened_by"][
            "evidence_sha256"
        ]
        red_run = self.add_command_artifact(
            paths,
            state,
            receipt,
            "round87-helper-red.json",
            role="red_run",
            finding_id=finding_id,
            red_test=red_test,
            execution_id="round87-helper-red-command",
            causal_parent={"kind": "finding_opening", "sha256": opening_sha256},
            exit_code=1,
            failures=1,
            classification="expected_failure_reproduced",
        )
        green_run = self.add_command_artifact(
            paths,
            state,
            receipt,
            "round87-helper-green.json",
            role="green_run",
            finding_id=finding_id,
            red_test=red_test,
            execution_id="round87-helper-green-command",
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

    def test_failed_gate_opens_one_carried_finding(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round87-open-") as temp_dir:
            _, _, state, finding = self.open_finding(Path(temp_dir))
            ledger = state["finding_ledger"]
            self.assertEqual([finding["finding_id"]], state["iterations"][-1]["carried_findings"])
            self.assertEqual("open", ledger[finding["finding_id"]]["status"])
            self.assertEqual(finding, ledger[finding["finding_id"]]["finding"])
            self.assertIsNone(ledger[finding["finding_id"]]["fix"])
            self.assertIsNone(ledger[finding["finding_id"]]["closure"])

    def test_carried_finding_cannot_pass_recheck_without_closure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round87-missing-") as temp_dir:
            graph, paths, state, finding = self.open_finding(Path(temp_dir))
            for step_id in (
                "preflight_snapshot",
                "adversarial_review",
            ):
                state = self.record_plain(graph, paths, state, step_id)
            state = self.record_typed_fix(
                graph, paths, state, finding["finding_id"]
            )
            state = self.record_plain(graph, paths, state, "deterministic_gate")
            accepted = {
                entry["step_id"]: entry["receipt"]["sha256"]
                for entry in state["iterations"][-1]["step_ledger"]
            }
            receipt, _ = graph.write_receipt(
                paths,
                state,
                "independent_recheck",
                dependency_receipts={"deterministic_gate": accepted["deterministic_gate"]},
            )
            with self.assertRaises(improvement_loop.LoopError) as raised:
                graph.record(paths, "independent_recheck", receipt)
            self.assertEqual("CARRIED_FINDING_NOT_CLOSED", raised.exception.code)

    def test_red_green_and_independent_recheck_close_the_finding(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round87-close-") as temp_dir:
            graph, paths, state, finding = self.open_finding(Path(temp_dir))
            finding_id = finding["finding_id"]
            state = self.record_plain(graph, paths, state, "preflight_snapshot")
            state = self.record_plain(graph, paths, state, "adversarial_review")
            state = self.authorize_fixture_fix(graph, paths, state)

            accepted = {
                entry["step_id"]: entry["receipt"]["sha256"]
                for entry in state["iterations"][-1]["step_ledger"]
            }
            receipt_path, _ = graph.write_receipt(
                paths,
                state,
                "red_green_fix",
                dependency_receipts={"adversarial_review": accepted["adversarial_review"]},
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            red_test = {
                "role": "red_test",
                "path": "skills/separating-facts-from-stories/tests/test_probe.py",
                "sha256": round86.sha256(paths["red_test"]),
            }
            receipt["artifacts"].append(red_test)
            opening_sha256 = state["finding_ledger"][finding_id]["opened_by"][
                "evidence_sha256"
            ]
            red_run = self.add_command_artifact(
                paths,
                state,
                receipt,
                "red-run.json",
                role="red_run",
                finding_id=finding_id,
                red_test={key: red_test[key] for key in ("path", "sha256")},
                execution_id="round87-red-command",
                causal_parent={
                    "kind": "finding_opening",
                    "sha256": opening_sha256,
                },
                exit_code=1,
                failures=1,
                classification="expected_failure_reproduced",
            )
            green_run = self.add_command_artifact(
                paths,
                state,
                receipt,
                "green-run.json",
                role="green_run",
                finding_id=finding_id,
                red_test={key: red_test[key] for key in ("path", "sha256")},
                execution_id="round87-green-command",
                causal_parent={
                    "kind": "red_run",
                    "sha256": red_run["sha256"],
                },
                exit_code=0,
                failures=0,
                classification="passed",
            )
            receipt["finding_events"] = [
                {
                    "action": "fix_claimed",
                    "finding_id": finding_id,
                    "red_test": {key: red_test[key] for key in ("path", "sha256")},
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
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            state = graph.record(paths, "red_green_fix", receipt_path)
            state = self.record_plain(graph, paths, state, "deterministic_gate")

            accepted = {
                entry["step_id"]: entry["receipt"]["sha256"]
                for entry in state["iterations"][-1]["step_ledger"]
            }
            recheck_path, _ = graph.write_receipt(
                paths,
                state,
                "independent_recheck",
                dependency_receipts={"deterministic_gate": accepted["deterministic_gate"]},
            )
            recheck_receipt = json.loads(recheck_path.read_text(encoding="utf-8"))
            recheck = self.add_command_artifact(
                paths,
                state,
                recheck_receipt,
                "independent-recheck.json",
                role="independent_recheck",
                finding_id=finding_id,
                red_test=state["finding_ledger"][finding_id]["red_test"],
                execution_id="round87-recheck-command",
                causal_parent={
                    "kind": "fix_event",
                    "sha256": state["finding_ledger"][finding_id]["fix"][
                        "event_sha256"
                    ],
                },
                exit_code=0,
                failures=0,
                classification="not_reproduced",
            )
            recheck_receipt["finding_events"] = [
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
            graph.sync_phase_payload(paths, recheck_receipt)
            recheck_path.write_text(
                json.dumps(recheck_receipt, indent=2) + "\n", encoding="utf-8"
            )
            state = graph.record(paths, "independent_recheck", recheck_path)

            finding_state = state["finding_ledger"][finding_id]
            self.assertEqual("closed", finding_state["status"])
            self.assertEqual(2, finding_state["closure"]["round"])
            self.assertEqual("source_freeze", state["iterations"][-1]["next_step"])

    def test_a_green_only_claim_is_not_a_red_green_closure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round87-green-only-") as temp_dir:
            graph, paths, state, finding = self.open_finding(Path(temp_dir))
            state = self.record_plain(graph, paths, state, "preflight_snapshot")
            state = self.record_plain(graph, paths, state, "adversarial_review")
            state = self.authorize_fixture_fix(graph, paths, state)
            accepted = {
                entry["step_id"]: entry["receipt"]["sha256"]
                for entry in state["iterations"][-1]["step_ledger"]
            }
            receipt_path, _ = graph.write_receipt(
                paths,
                state,
                "red_green_fix",
                dependency_receipts={"adversarial_review": accepted["adversarial_review"]},
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            red_test = {
                "path": "skills/separating-facts-from-stories/tests/test_probe.py",
                "sha256": round86.sha256(paths["red_test"]),
            }
            receipt["artifacts"].append({"role": "red_test", **red_test})
            green = self.add_command_artifact(
                paths,
                state,
                receipt,
                "only-green.json",
                role="green_run",
                finding_id=finding["finding_id"],
                red_test=red_test,
                execution_id="round87-only-green-command",
                causal_parent={
                    "kind": "finding_opening",
                    "sha256": state["finding_ledger"][finding["finding_id"]][
                        "opened_by"
                    ]["evidence_sha256"],
                },
                exit_code=0,
                failures=0,
                classification="passed",
            )
            receipt["finding_events"] = [
                {
                    "action": "fix_claimed",
                    "finding_id": finding["finding_id"],
                    "red_test": {
                        "path": red_test["path"],
                        "sha256": red_test["sha256"],
                    },
                    "red_run": {
                        "path": green["path"],
                        "sha256": green["sha256"],
                    },
                    "green_run": {
                        "path": green["path"],
                        "sha256": green["sha256"],
                    },
                }
            ]
            graph.sync_phase_payload(paths, receipt)
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(improvement_loop.LoopError) as raised:
                graph.record(paths, "red_green_fix", receipt_path)
            self.assertEqual("FINDING_CLOSURE_INVALID", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
