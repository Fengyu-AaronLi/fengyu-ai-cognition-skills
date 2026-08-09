from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import improvement_loop  # noqa: E402
import test_round29_improvement_loop_red as round29  # noqa: E402
from host_execution_fixture import write_host_review  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Round86WorkflowStepLedgerRedTests(unittest.TestCase):
    """A graph workflow needs ordered, content-addressed execution receipts."""

    def make_graph_candidate(self, root: Path) -> tuple[dict[str, Path], dict]:
        helper = round29.Round29ImprovementLoopRedTests()
        paths = helper.make_candidate(root)
        workflow = paths["workflow"]
        text = workflow.read_text(encoding="utf-8").replace(
            '  source_manifest: "workflows/separating-facts-release-sources.json"\n',
            '  source_manifest: "workflows/separating-facts-release-sources.json"\n'
            '  execution_mode: "execution_graph"\n'
            '  stop_authority: "controller_prove_stop"\n'
            '  gate_producer: "skills/separating-facts-from-stories/scripts/produce_release_gate.py"\n',
            1,
        )
        workflow.write_text(text, encoding="utf-8")
        producer = paths["controller"].with_name("produce_release_gate.py")
        producer.write_text("# producer fixture\n", encoding="utf-8")
        graph_worker = paths["controller"].with_name("graph_phase_worker.py")
        shutil.copy2(SKILL_DIR / "scripts" / "graph_phase_worker.py", graph_worker)
        host_runtime = paths["controller"].with_name("codex_exec_host.py")
        shutil.copy2(SKILL_DIR / "scripts" / "codex_exec_host.py", host_runtime)
        manifest = json.loads(paths["source_manifest"].read_text(encoding="utf-8"))
        manifest["source_files"].append(producer.relative_to(paths["repo"]).as_posix())
        manifest["source_files"].append(
            graph_worker.relative_to(paths["repo"]).as_posix()
        )
        manifest["source_files"].append(
            host_runtime.relative_to(paths["repo"]).as_posix()
        )
        manifest["source_files"] = sorted(set(manifest["source_files"]))
        paths["source_manifest"].write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        governance = {
            paths["workflow"].relative_to(paths["repo"]).as_posix(),
            paths["controller"].relative_to(paths["repo"]).as_posix(),
            paths["source_manifest"].relative_to(paths["repo"]).as_posix(),
        }
        source_files = [item for item in manifest["source_files"] if item not in governance]
        with redirect_stdout(StringIO()):
            improvement_loop.command_start(
                argparse.Namespace(
                    repo_root=str(paths["repo"]),
                    workflow="workflows/separating-facts-loop.yaml",
                    state_dir=".ao-output/loop-run",
                    source_file=source_files,
                    allow_write=[
                        "skills/separating-facts-from-stories",
                        "workflows",
                        ".ao-output",
                    ],
                    max_rounds=3,
                )
            )
        state = json.loads(
            (paths["state_dir"] / "loop-state.json").read_text(encoding="utf-8")
        )
        return paths, state

    def review_phase_result(
        self,
        paths: dict[str, Path],
        *,
        source_sha256: str,
        step_id: str,
        findings: list[dict] | None = None,
    ) -> dict:
        reports: list[tuple[Path, dict]] = []
        for index, attestation_type in enumerate(
            ("p0_zero", "reproducible_p1_zero")
        ):
            reports.append(
                write_host_review(
                    paths["repo"],
                    attestation_type,
                    source_sha256,
                    findings=findings,
                    suffix=f"{step_id}-{index}-{uuid.uuid4().hex}",
                )
            )
        return {
            "review_attestations": [
                {
                    "attestation_type": report["attestation_type"],
                    "path": path.relative_to(paths["repo"].resolve()).as_posix(),
                    "sha256": sha256(path),
                }
                for path, report in reports
            ],
            "reviewer_ids": [report["reviewer_id"] for _, report in reports],
            "execution_ids": [report["execution_id"] for _, report in reports],
            "raw_artifact_sha256s": [
                report["review_artifact"]["sha256"] for _, report in reports
            ],
            "finding_ids": sorted(
                item["finding_id"] for item in list(findings or [])
            ),
            "trust_boundary": improvement_loop.REVIEW_TRUST_BOUNDARY,
        }

    def write_receipt(
        self,
        paths: dict[str, Path],
        state: dict,
        step_id: str,
        *,
        dependency_receipts: dict[str, str] | None = None,
    ) -> tuple[Path, Path]:
        artifact = paths["state_dir"] / f"{step_id}.artifact.json"
        iteration = state["iterations"][-1]
        pending_epoch = iteration.get("pending_source_epoch")
        receipt_source_sha256 = (
            pending_epoch["source_after_sha256"]
            if step_id == "red_green_fix" and isinstance(pending_epoch, dict)
            else iteration["active_source_sha256"]
        )
        result = self.phase_result(paths, state, step_id)
        artifact.write_text(
            json.dumps(
                {
                    "schema_version": improvement_loop.SCHEMA_VERSION,
                    "evidence_type": f"{step_id}.v1",
                    "controller_run_id": state["controller_run_id"],
                    "iteration_id": state["iterations"][-1]["iteration_id"],
                    "source_sha256": receipt_source_sha256,
                    "result": result,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        receipt = {
            "schema_version": "1.1.0",
            "receipt_type": "phase_receipt.v1",
            "controller_run_id": state["controller_run_id"],
            "attempt_id": "unbound-fixture-attempt",
            "work_order": None,
            "iteration_id": state["iterations"][-1]["iteration_id"],
            "source_sha256": receipt_source_sha256,
            "step_id": step_id,
            "status": "succeeded",
            "dependency_receipts": dependency_receipts or {},
            "producer": {
                "actor_id": f"round86-{step_id}-actor",
                "execution_id": f"round86-{step_id}",
                "trust_boundary": "local_attestation_only_not_cryptographic_signature",
            },
            "summary": f"Recorded {step_id} evidence.",
            "artifacts": [
                {
                    "role": improvement_loop.PHASE_PRIMARY_ROLES[step_id],
                    "path": artifact.relative_to(paths["repo"]).as_posix(),
                    "sha256": sha256(artifact),
                }
            ],
            "finding_events": [],
        }
        receipt_path = paths["state_dir"] / f"{step_id}.receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        return receipt_path, artifact

    def phase_result(self, paths: dict[str, Path], state: dict, step_id: str) -> dict:
        iteration = state["iterations"][-1]
        pending_epoch = iteration.get("pending_source_epoch")
        source_sha256 = iteration["active_source_sha256"]
        if step_id == "preflight_snapshot":
            controller = state["workflow_policy"]["controller_executable"]
            return {
                "source_file_count": len(state["source_files"]),
                "source_manifest_sha256": state["source_manifest"]["sha256"],
                "workflow_sha256": state["workflow"]["sha256"],
                "controller_sha256": state["source_snapshot"]["files"][controller],
                "tests_root": "skills/separating-facts-from-stories/tests",
                "protected_changes": [],
                "denied_operations": sorted(
                    state["workflow_policy"]["denied_operations"]
                ),
            }
        if step_id in {"adversarial_review", "independent_recheck"}:
            return self.review_phase_result(
                paths,
                source_sha256=source_sha256,
                step_id=step_id,
            )
        if step_id == "red_green_fix":
            before_source_sha256 = source_sha256
            after_source_sha256 = (
                pending_epoch["source_after_sha256"]
                if isinstance(pending_epoch, dict)
                else source_sha256
            )
            red_source_sha256 = (
                pending_epoch["red_source_sha256"]
                if isinstance(pending_epoch, dict)
                else source_sha256
            )
            return {
                "before_source_sha256": before_source_sha256,
                "red_source_sha256": red_source_sha256,
                "after_source_sha256": after_source_sha256,
                "fixed_finding_ids": [],
                "full_regression": {
                    "tests_run": 1,
                    "failures": 0,
                    "errors": 0,
                    "skipped": 0,
                    "exit_code": 0,
                },
            }
        if step_id == "deterministic_gate":
            return {
                "commands": [
                    {
                        "name": name,
                        "exit_code": 0,
                        "tests_run": 1,
                        "failures": 0,
                        "errors": 0,
                        "skipped": 0,
                    }
                    for name in (
                        "unit_tests",
                        "self_test",
                        "markdown_links",
                        "workflow_lifecycle",
                    )
                ]
            }
        if step_id == "source_freeze":
            return {
                "source_sha256": source_sha256,
                "source_file_count": len(state["source_files"]),
                "source_manifest_sha256": state["source_manifest"]["sha256"],
                "open_finding_ids": sorted(
                    finding_id
                    for finding_id, item in state["finding_ledger"].items()
                    if item["status"] == "open"
                ),
            }
        if step_id == "frozen_eval_prepare":
            return {
                "root_was_absent": True,
                "case_count": 18,
                "output_count": 0,
                "suite_sha256": "3" * 64,
                "evaluation_context_sha256": "4" * 64,
            }
        if step_id == "isolated_eval":
            return {
                "case_count": 18,
                "runner_ids": [f"runner-{index:02d}" for index in range(18)],
                "execution_ids": [f"execution-{index:02d}" for index in range(18)],
                "trust_boundary": "external_dispatch_attestation_not_isolation_proof",
            }
        if step_id == "eval_audit":
            return {
                "valid": True,
                "case_count": 18,
                "artifact_count": 16,
                "missing": [],
                "suite_errors": [],
            }
        raise AssertionError(f"no fixture phase payload for {step_id}")

    def sync_phase_payload(self, paths: dict[str, Path], receipt: dict) -> None:
        role = improvement_loop.PHASE_PRIMARY_ROLES[receipt["step_id"]]
        descriptor = next(item for item in receipt["artifacts"] if item["role"] == role)
        path = paths["repo"] / descriptor["path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        events = receipt["finding_events"]
        if receipt["step_id"] == "adversarial_review":
            open_events = [item for item in events if item.get("action") == "open"]
            host_findings = [
                {
                    "finding_id": item["finding_id"],
                    "severity": item["severity"],
                    "summary": item["summary"],
                    "reproducer": item["reproducer"],
                    "actual": item["actual"],
                    "expected": item["expected"],
                    "reproducible": True,
                    "status": "open",
                }
                for item in open_events
            ]
            payload["result"] = self.review_phase_result(
                paths,
                source_sha256=receipt["source_sha256"],
                step_id=receipt["step_id"],
                findings=host_findings,
            )
        elif receipt["step_id"] == "red_green_fix":
            payload["result"]["fixed_finding_ids"] = sorted(
                item["finding_id"]
                for item in events
                if item.get("action") == "fix_claimed"
            )
        elif receipt["step_id"] == "independent_recheck":
            payload["result"]["finding_ids"] = sorted(
                item["finding_id"] for item in events if item.get("action") == "close"
            )
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        descriptor["sha256"] = sha256(path)

    def begin_and_bind(
        self, paths: dict[str, Path], step_id: str, receipt: Path
    ) -> dict:
        with redirect_stdout(StringIO()):
            improvement_loop.command_begin_step(
                argparse.Namespace(
                    state_dir=str(paths["state_dir"]),
                    step_id=step_id,
                )
            )
        state = json.loads(
            (paths["state_dir"] / "loop-state.json").read_text(encoding="utf-8")
        )
        active = state["iterations"][-1]["active_work_order"]
        document = json.loads(receipt.read_text(encoding="utf-8"))
        document["controller_run_id"] = state["controller_run_id"]
        document["attempt_id"] = active["attempt_id"]
        document["work_order"] = {
            "path": active["path"],
            "sha256": active["sha256"],
        }
        receipt.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return state

    def record(
        self,
        paths: dict[str, Path],
        step_id: str,
        receipt: Path,
        *,
        auto_begin: bool = True,
    ) -> dict:
        if auto_begin:
            self.begin_and_bind(paths, step_id, receipt)
        with redirect_stdout(StringIO()):
            improvement_loop.command_record_step(
                argparse.Namespace(
                    state_dir=str(paths["state_dir"]),
                    step_id=step_id,
                    receipt=receipt.relative_to(paths["repo"]).as_posix(),
                )
            )
        return json.loads(
            (paths["state_dir"] / "loop-state.json").read_text(encoding="utf-8")
        )

    def test_out_of_order_step_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round86-order-") as temp_dir:
            paths, state = self.make_graph_candidate(Path(temp_dir))
            receipt, _ = self.write_receipt(paths, state, "adversarial_review")
            with self.assertRaises(improvement_loop.LoopError) as raised:
                self.record(paths, "adversarial_review", receipt)
            self.assertEqual("WORKFLOW_STEP_OUT_OF_ORDER", raised.exception.code)

    def test_valid_receipt_advances_and_is_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round86-advance-") as temp_dir:
            paths, state = self.make_graph_candidate(Path(temp_dir))
            receipt, _ = self.write_receipt(paths, state, "preflight_snapshot")
            updated = self.record(paths, "preflight_snapshot", receipt)

            iteration = updated["iterations"][-1]
            self.assertEqual("adversarial_review", iteration["next_step"])
            self.assertEqual(1, len(iteration["step_ledger"]))
            entry = iteration["step_ledger"][0]
            self.assertEqual("preflight_snapshot", entry["step_id"])
            self.assertEqual(sha256(receipt), entry["receipt"]["sha256"])
            self.assertEqual(
                receipt.relative_to(paths["repo"]).as_posix(),
                entry["receipt"]["path"],
            )

    def test_receipt_or_artifact_tamper_breaks_state_loading(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round86-tamper-") as temp_dir:
            paths, state = self.make_graph_candidate(Path(temp_dir))
            receipt, artifact = self.write_receipt(paths, state, "preflight_snapshot")
            self.record(paths, "preflight_snapshot", receipt)

            artifact.write_text('{"step_id":"tampered"}\n', encoding="utf-8")
            with self.assertRaises(improvement_loop.LoopError) as raised:
                improvement_loop.load_state(paths["state_dir"])
            self.assertEqual("STATE_EVIDENCE_INVALID", raised.exception.code)

    def test_prove_stop_fails_before_path_checks_when_steps_are_incomplete(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round86-prove-") as temp_dir:
            paths, _ = self.make_graph_candidate(Path(temp_dir))
            with self.assertRaises(improvement_loop.LoopError) as raised:
                improvement_loop.command_prove_stop(
                    argparse.Namespace(
                        state_dir=str(paths["state_dir"]),
                        eval_root="missing-eval-root",
                        p0_review="missing-p0.json",
                        p1_review="missing-p1.json",
                    )
                )
            self.assertEqual("WORKFLOW_STEPS_INCOMPLETE", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
