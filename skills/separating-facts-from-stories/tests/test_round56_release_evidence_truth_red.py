from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[1]
LOOP_PATH = SKILL_DIR / "scripts" / "improvement_loop.py"
PRODUCER_PATH = SKILL_DIR / "scripts" / "produce_release_gate.py"
PACKAGER_PATH = SKILL_DIR / "scripts" / "package_runtime.py"
RUNNER_PATH = SKILL_DIR / "scripts" / "run_evals.py"
SOURCE_MANIFEST_PATH = REPO_ROOT / "workflows" / "separating-facts-release-sources.json"
REQUIRED_REVIEW_SCOPE = (
    "runtime_semantics",
    "safety_routing",
    "state_integrity",
    "release_evidence",
    "packaging_installation",
    "documentation_claims",
)

sys.path.insert(0, str(SKILL_DIR / "tests"))
import test_round29_improvement_loop_red as round29  # noqa: E402
import test_round86_workflow_step_ledger_red as round86  # noqa: E402
from host_execution_fixture import prepare_review_source, write_host_review  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Round56ReleaseEvidenceTruthRedTests(unittest.TestCase):
    maxDiff = None

    def test_authoritative_manifest_closes_over_both_release_evidence_sets(self) -> None:
        packager = load_module("round56_packager", PACKAGER_PATH)
        runner = load_module("round56_runner", RUNNER_PATH)
        manifest = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
        declared = set(manifest["source_files"])

        def normalized(values: dict[str, str]) -> set[str]:
            return {
                f"skills/separating-facts-from-stories/{Path(value).as_posix()}"
                for value in values.values()
            }

        required = normalized(packager.RELEASE_EVIDENCE_FILES) | normalized(
            runner.RELEASE_EVIDENCE_FILES
        )
        self.assertEqual([], sorted(required - declared))
        self.assertEqual(
            manifest["source_files"],
            sorted(set(manifest["source_files"])),
            "the authoritative source list must remain normalized, sorted, and unique",
        )

    def test_documented_historical_raw_evidence_is_frozen_by_the_manifest(self) -> None:
        manifest = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
        declared = set(manifest["source_files"])
        roots = (
            SKILL_DIR / "evals" / "raw" / "baseline",
            SKILL_DIR / "evals" / "raw" / "with-skill",
            SKILL_DIR / "evals" / "raw" / "runtime-integration-v23-workplace",
        )
        expected = {
            path.relative_to(REPO_ROOT).as_posix()
            for root in roots
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        self.assertEqual(19, len(expected))
        self.assertEqual([], sorted(expected - declared))

    def test_v4_fixture_drift_during_prove_stop_blocks_stop(self) -> None:
        loop = load_module("round56_v4_drift", LOOP_PATH)
        helper = round29.Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round56-v4-drift-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            workflow_text = paths["workflow"].read_text(encoding="utf-8")
            workflow_text = workflow_text.replace(
                '  source_manifest: "workflows/separating-facts-release-sources.json"\n',
                '  source_manifest: "workflows/separating-facts-release-sources.json"\n'
                '  execution_mode: "execution_graph"\n'
                '  stop_authority: "controller_prove_stop"\n'
                '  gate_producer: "skills/separating-facts-from-stories/scripts/produce_release_gate.py"\n',
            )
            paths["workflow"].write_text(workflow_text, encoding="utf-8")
            producer = paths["controller"].with_name("produce_release_gate.py")
            producer.write_text("# producer fixture\n", encoding="utf-8")
            v4_fixture = (
                paths["repo"]
                / "skills/separating-facts-from-stories/evals/raw/with-skill-v4-capability"
                / "machine-report.json"
            )
            v4_fixture.parent.mkdir(parents=True)
            v4_fixture.write_text('{"valid": true}\n', encoding="utf-8")
            manifest = json.loads(paths["source_manifest"].read_text(encoding="utf-8"))
            manifest["source_files"].extend(
                [
                    producer.relative_to(paths["repo"]).as_posix(),
                    v4_fixture.relative_to(paths["repo"]).as_posix(),
                ]
            )
            manifest["source_files"] = sorted(set(manifest["source_files"]))
            paths["source_manifest"].write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            source_files = [
                value
                for value in manifest["source_files"]
                if value
                not in {
                    paths["workflow"].relative_to(paths["repo"]).as_posix(),
                    paths["controller"].relative_to(paths["repo"]).as_posix(),
                    paths["source_manifest"].relative_to(paths["repo"]).as_posix(),
                }
            ]
            with redirect_stdout(io.StringIO()):
                loop.command_start(
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
            for step_id, direct_dependencies in loop.REQUIRED_EXECUTION_GRAPH[:9]:
                state = json.loads(
                    (paths["state_dir"] / "loop-state.json").read_text(encoding="utf-8")
                )
                with redirect_stdout(io.StringIO()):
                    loop.command_begin_step(
                        argparse.Namespace(
                            state_dir=str(paths["state_dir"]),
                            step_id=step_id,
                        )
                    )
                state = json.loads(
                    (paths["state_dir"] / "loop-state.json").read_text(encoding="utf-8")
                )
                active_work_order = state["iterations"][-1]["active_work_order"]
                accepted = {
                    entry["step_id"]: entry["receipt"]["sha256"]
                    for entry in state["iterations"][-1]["step_ledger"]
                }
                artifact = paths["state_dir"] / f"{step_id}.artifact.json"
                phase_result = round86.Round86WorkflowStepLedgerRedTests().phase_result(
                    paths, state, step_id
                )
                artifact.write_text(
                    json.dumps(
                        {
                            "schema_version": loop.SCHEMA_VERSION,
                            "evidence_type": f"{step_id}.v1",
                            "controller_run_id": state["controller_run_id"],
                            "iteration_id": state["iterations"][-1]["iteration_id"],
                            "source_sha256": state["source_snapshot"]["sha256"],
                            "result": phase_result,
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                receipt = {
                    "schema_version": "1.1.0",
                    "receipt_type": "phase_receipt.v1",
                    "controller_run_id": state["controller_run_id"],
                    "attempt_id": active_work_order["attempt_id"],
                    "work_order": {
                        "path": active_work_order["path"],
                        "sha256": active_work_order["sha256"],
                    },
                    "iteration_id": state["iterations"][-1]["iteration_id"],
                    "source_sha256": state["source_snapshot"]["sha256"],
                    "step_id": step_id,
                    "status": "succeeded",
                    "dependency_receipts": {
                        dependency: accepted[dependency]
                        for dependency in direct_dependencies
                    },
                    "producer": {
                        "actor_id": "round56-fixture",
                        "execution_id": f"round56-{step_id}",
                        "trust_boundary": "local_attestation_only_not_cryptographic_signature",
                    },
                    "summary": f"Fixture evidence for {step_id}.",
                    "artifacts": [
                        {
                            "role": loop.PHASE_PRIMARY_ROLES[step_id],
                            "path": artifact.relative_to(paths["repo"]).as_posix(),
                            "sha256": sha256(artifact),
                        }
                    ],
                    "finding_events": [],
                }
                receipt_path = paths["state_dir"] / f"{step_id}.receipt.json"
                receipt_path.write_text(
                    json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
                )
                with redirect_stdout(io.StringIO()):
                    loop.command_record_step(
                        argparse.Namespace(
                            state_dir=str(paths["state_dir"]),
                            step_id=step_id,
                            receipt=receipt_path.relative_to(paths["repo"]).as_posix(),
                        )
                    )
            eval_root = paths["repo"] / "eval-root"
            eval_root.mkdir()
            state = json.loads(
                (paths["state_dir"] / "loop-state.json").read_text(encoding="utf-8")
            )
            recheck_entry = next(
                item
                for item in state["iterations"][-1]["step_ledger"]
                if item["step_id"] == "independent_recheck"
            )
            recheck_primary = next(
                item
                for item in recheck_entry["artifacts"]
                if item["role"] == loop.PHASE_PRIMARY_ROLES["independent_recheck"]
            )
            recheck_payload = json.loads(
                (paths["repo"] / recheck_primary["path"]).read_text(encoding="utf-8")
            )
            review_by_type = {
                item["attestation_type"]: paths["repo"] / item["path"]
                for item in recheck_payload["result"]["review_attestations"]
            }
            p0_review = review_by_type["p0_zero"]
            p1_review = review_by_type["reproducible_p1_zero"]

            def mutate_fixture(*args, **kwargs):
                v4_fixture.write_text('{"valid": false}\n', encoding="utf-8")
                return subprocess.CompletedProcess(
                    args[0], 0, json.dumps({"valid": True, "gate": "unused.json"}), ""
                )

            with mock.patch.object(loop, "_run_in_process_group", side_effect=mutate_fixture):
                with self.assertRaises(loop.LoopError) as raised:
                    loop.command_prove_stop(
                        argparse.Namespace(
                            state_dir=str(paths["state_dir"]),
                            eval_root="eval-root",
                            p0_review=p0_review.relative_to(paths["repo"]).as_posix(),
                            p1_review=p1_review.relative_to(paths["repo"]).as_posix(),
                        )
                    )
            self.assertEqual("SOURCE_DRIFT_DURING_PROOF", raised.exception.code)
            state = json.loads(
                (paths["state_dir"] / "loop-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual("active", state["status"])
            self.assertIsNone(state["decision"])

    def _write_review_artifact(self, root: Path, name: str, text: str) -> dict[str, str]:
        path = root / name
        path.write_text(text, encoding="utf-8")
        return {"path": path.name, "sha256": sha256(path)}

    def _report(
        self,
        root: Path,
        *,
        attestation_type: str,
        reviewer_id: str,
        execution_id: str,
        artifact_name: str,
        artifact_text: str,
    ) -> dict[str, object]:
        del reviewer_id, execution_id, artifact_text
        source_sha = prepare_review_source(root)
        _, report = write_host_review(
            root,
            attestation_type,
            source_sha,
            suffix=Path(artifact_name).stem,
        )
        return report

    def test_review_pair_binds_distinct_reviewers_executions_and_raw_artifacts(self) -> None:
        producer = load_module("round56_review_valid", PRODUCER_PATH)
        with tempfile.TemporaryDirectory(prefix="sffs-round56-review-") as temp_dir:
            root = Path(temp_dir)
            p0 = self._report(
                root,
                attestation_type="p0_zero",
                reviewer_id="reviewer-a",
                execution_id="execution-a",
                artifact_name="p0-raw.md",
                artifact_text="Independent P0 review raw notes.\n",
            )
            p1 = self._report(
                root,
                attestation_type="reproducible_p1_zero",
                reviewer_id="reviewer-b",
                execution_id="execution-b",
                artifact_name="p1-raw.md",
                artifact_text="Independent P1 review raw notes.\n",
            )
            try:
                result = producer.validate_review_pair(
                    p0, p1, source_sha256=p0["source_sha256"], repo_root=root
                )
            except (TypeError, ValueError) as exc:
                self.fail(f"valid structured review pair was rejected: {exc}")
            self.assertEqual((0, 0), result)

    def test_review_pair_rejects_same_reviewer_or_execution(self) -> None:
        producer = load_module("round56_review_independence", PRODUCER_PATH)
        with tempfile.TemporaryDirectory(prefix="sffs-round56-independent-") as temp_dir:
            root = Path(temp_dir)
            p0 = self._report(
                root,
                attestation_type="p0_zero",
                reviewer_id="reviewer-a",
                execution_id="execution-a",
                artifact_name="p0.md",
                artifact_text="P0 notes\n",
            )
            p1 = self._report(
                root,
                attestation_type="reproducible_p1_zero",
                reviewer_id="reviewer-b",
                execution_id="execution-b",
                artifact_name="p1.md",
                artifact_text="P1 notes\n",
            )
            for field in ("reviewer_id", "execution_id"):
                with self.subTest(field=field):
                    candidate = dict(p1)
                    candidate[field] = p0[field]
                    with self.assertRaisesRegex(
                        ValueError, "host execution receipt|do not match"
                    ):
                        producer.validate_review_pair(
                            p0, candidate, source_sha256=p0["source_sha256"], repo_root=root
                        )

    def test_review_pair_rejects_copied_missing_or_symlink_artifacts(self) -> None:
        producer = load_module("round56_review_artifacts", PRODUCER_PATH)
        with tempfile.TemporaryDirectory(prefix="sffs-round56-artifact-") as temp_dir:
            root = Path(temp_dir)
            p0 = self._report(
                root,
                attestation_type="p0_zero",
                reviewer_id="reviewer-a",
                execution_id="execution-a",
                artifact_name="p0.md",
                artifact_text="same raw notes\n",
            )
            p1 = self._report(
                root,
                attestation_type="reproducible_p1_zero",
                reviewer_id="reviewer-b",
                execution_id="execution-b",
                artifact_name="p1.md",
                artifact_text="same raw notes\n",
            )
            copied = dict(p1)
            copied["review_artifact"] = p0["review_artifact"]
            with self.assertRaisesRegex(ValueError, "host execution receipt|do not match"):
                producer.validate_review_pair(
                    p0, copied, source_sha256=p0["source_sha256"], repo_root=root
                )

            missing = dict(p1)
            missing["review_artifact"] = {"path": "missing.md", "sha256": "b" * 64}
            with self.assertRaisesRegex(ValueError, "artifact"):
                producer.validate_review_pair(
                    p0, missing, source_sha256=p0["source_sha256"], repo_root=root
                )
            omitted = dict(p1)
            omitted.pop("review_artifact")
            with self.assertRaises(ValueError):
                producer.validate_review_pair(
                    p0, omitted, source_sha256=p0["source_sha256"], repo_root=root
                )

            target = root / "outside.md"
            target.write_text("outside\n", encoding="utf-8")
            link = root / "linked.md"
            link.symlink_to(target)
            symlinked = dict(p1)
            symlinked["review_artifact"] = {"path": link.name, "sha256": sha256(target)}
            with self.assertRaisesRegex(ValueError, "symlink"):
                producer.validate_review_pair(
                    p0, symlinked, source_sha256=p0["source_sha256"], repo_root=root
                )

    def test_review_attestation_rejects_missing_or_empty_scope_and_environment(self) -> None:
        producer = load_module("round56_review_scope", PRODUCER_PATH)
        with tempfile.TemporaryDirectory(prefix="sffs-round56-scope-") as temp_dir:
            root = Path(temp_dir)
            report = self._report(
                root,
                attestation_type="p0_zero",
                reviewer_id="reviewer-a",
                execution_id="execution-a",
                artifact_name="p0.md",
                artifact_text="P0 notes\n",
            )
            mutations = (
                ("review_scope", []),
                ("review_scope", list(REQUIRED_REVIEW_SCOPE[:-1])),
                ("model_environment", {}),
                ("model_environment", {"runner": "", "model": "m", "isolation": "i"}),
            )
            for field, value in mutations:
                with self.subTest(field=field, value=value):
                    candidate = dict(report)
                    candidate[field] = value
                    with self.assertRaisesRegex(ValueError, "scope|environment"):
                        producer.derive_review_open_count(
                            candidate,
                            expected_type="p0_zero",
                            source_sha256=report["source_sha256"],
                            repo_root=root,
                        )
            for missing_field in ("review_scope", "model_environment"):
                with self.subTest(missing_field=missing_field):
                    candidate = dict(report)
                    candidate.pop(missing_field)
                    with self.assertRaises(ValueError):
                        producer.derive_review_open_count(
                            candidate,
                            expected_type="p0_zero",
                            source_sha256=report["source_sha256"],
                            repo_root=root,
                        )

    def test_rollback_proof_uses_only_file_level_original_path_absence(self) -> None:
        loop = load_module("round56_rollback_truth", LOOP_PATH)
        base = {
            "operation": "file_level_rollback_and_restore",
            "installed_path": "/tmp/clean-target/separating-facts-from-stories",
            "baseline_state_sha256": "1" * 64,
            "rolled_back_state_sha256": "1" * 64,
            "install_absent_during_rollback": True,
            "original_path_absent_in_fresh_python_process": True,
            "restore_verified": True,
            "installed_manifest_sha256": "2" * 64,
            "restored_manifest_sha256": "2" * 64,
        }
        document = {
            "gate_check": "rollback",
            "passed": True,
            "proof": base,
            "commands": [
                {"argv": ["python", str(index)], "exit_code": 0}
                for index in range(3)
            ],
            "artifacts": [{"role": "rollback_receipt"}],
        }
        loop.validate_typed_gate_proof(
            "rollback", document, evidence_relative="rollback.json"
        )

        old = dict(base)
        old["discovery_absent_in_fresh_process"] = old.pop(
            "original_path_absent_in_fresh_python_process"
        )
        with self.assertRaises(loop.LoopError):
            loop.validate_typed_gate_proof(
                "rollback",
                {**document, "proof": old},
                evidence_relative="rollback.json",
            )

        fake_host_claim = dict(base)
        fake_host_claim["host_discovery_verified"] = True
        fake_host_claim["disabled_directories_scanned"] = True
        with self.assertRaises(loop.LoopError):
            loop.validate_typed_gate_proof(
                "rollback",
                {**document, "proof": fake_host_claim},
                evidence_relative="rollback.json",
            )


if __name__ == "__main__":
    unittest.main()
