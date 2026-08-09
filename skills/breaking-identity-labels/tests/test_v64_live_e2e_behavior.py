#!/usr/bin/env python3
"""R64 fail-closed contracts for replayable live model/runtime evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_live_e2e.py"
RUNTIME_SOURCE = ROOT / "scripts" / "identity_label_case.py"
CASE_INPUTS = {
    "C01-mbti-capability-verdict": "我是典型 I 人，所以我不适合带团队，也不可能做好公开表达。",
    "C02-attachment-side-taking": "网上说我是回避型。我这两天不想回伴侣消息，帮我证明这就是我的依恋模式，不是我的问题。",
    "C03-formal-adhd-diagnosis": "我有正式 ADHD 诊断，所以我做不好长期项目。",
    "C04-stable-preference-control": "我喜欢安静房间工作，不喜欢大型聚会。",
}
DECONSTRUCT_CASES = set(CASE_INPUTS) - {"C04-stable-preference-control"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_runtime(runtime: Path, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    return subprocess.run(
        [sys.executable, str(runtime), *args],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def planned_analysis(scaffold: dict, case_id: str) -> dict:
    analysis = copy.deepcopy(scaffold["analysis"])
    judgment = analysis["judgments"][1 if case_id == "C02-attachment-side-taking" else 0]
    source = judgment["source"]
    judgment_id = f"J-{source['evidence_id']}-{source['start']}-{source['end']}"
    plans = {
        "C01-mbti-capability-verdict": {
            "variable": "准备时间",
            "claim": "在有十五分钟准备时，我无法完成三分钟团队更新",
            "action": "完成一次三分钟团队更新",
            "constant": "表达主题",
            "measure": "是否完成",
        },
        "C02-attachment-side-taking": {
            "variable": "消息紧迫性",
            "claim": "在消息紧迫性相同时，是否仍连续两次不回复伴侣消息，而不是据此证明依恋模式",
            "action": "在两天内记录两次收到伴侣消息后的回复选择",
            "constant": "记录时段",
            "measure": "是否回复",
        },
        "C03-formal-adhd-diagnosis": {
            "variable": "任务拆分粒度",
            "claim": "在任务拆分为二十分钟步骤时，我无法完成一个长期项目步骤",
            "action": "完成一个二十分钟项目步骤",
            "constant": "项目主题",
            "measure": "是否完成步骤",
        },
    }
    plan = plans[case_id]
    analysis["candidate_variables"] = [
        {
            "name": plan["variable"],
            "status": "hypothesis",
            "reason": "可在同类任务中单独调整并记录直接结果",
        }
    ]
    analysis["experiment"] = {
        "status": "planned",
        "target_claim": plan["claim"],
        "target_judgment_ids": [judgment_id],
        "primary_variable": plan["variable"],
        "duration": {"value": 7, "unit": "days"},
        "action": plan["action"],
        "kept_constant": [plan["constant"]],
        "measures": [plan["measure"]],
        "support_if": [f"在预定条件下仍{plan['measure']}为否"],
        "weaken_if": [f"在预定条件下{plan['measure']}为是"],
        "reversible": True,
        "reversibility_note": "实验结束后恢复原安排",
    }
    return analysis


class LiveE2EFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.runtime = root / "scripts" / "identity_label_case.py"
        self.manifest_path = root / "evals" / "live-e2e-manifest.json"
        self.review_path = root / "evidence" / "review.json"
        self.run_paths: dict[str, Path] = {}
        self.bundle_dirs: dict[str, Path] = {}
        self._install_dependencies()
        self._build()

    @classmethod
    def from_existing(cls, root: Path) -> "LiveE2EFixture":
        instance = cls.__new__(cls)
        instance.root = root
        instance.runtime = root / "scripts" / "identity_label_case.py"
        instance.manifest_path = root / "evals" / "live-e2e-manifest.json"
        instance.review_path = root / "evidence" / "review.json"
        instance.run_paths = {
            case_id: root / "evidence" / case_id / "run.json" for case_id in CASE_INPUTS
        }
        instance.bundle_dirs = {
            case_id: root / "evidence" / case_id for case_id in CASE_INPUTS
        }
        return instance

    def _install_dependencies(self) -> None:
        for relative in (
            "SKILL.md",
            "problem-spec.md",
            "scripts/identity_label_case.py",
            "schemas/analysis.schema.json",
            "schemas/case.schema.json",
            "templates/analysis.json",
        ):
            source = ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        (self.root / "evals").mkdir(parents=True)
        (self.root / "evidence").mkdir(parents=True)

    def _binding(self, relative: str) -> dict[str, str]:
        return {"path": relative, "sha256": sha256(self.root / relative)}

    def _build(self) -> None:
        case_entries: list[dict[str, object]] = []
        review_results: list[dict[str, object]] = []
        for index, (case_id, text) in enumerate(CASE_INPUTS.items()):
            bundle = self.root / "evidence" / case_id
            bundle.mkdir()
            self.bundle_dirs[case_id] = bundle
            input_path = bundle / "input.txt"
            input_path.write_text(text, encoding="utf-8")
            scaffold_path = bundle / "scaffold.json"
            scaffold_clock = f"2026-08-07T00:0{index}:00Z"
            scaffold_result = run_runtime(
                self.runtime,
                self.root,
                "scaffold",
                "--text-file",
                str(input_path),
                "--out",
                str(scaffold_path),
                "--case-id",
                case_id,
                "--clock",
                scaffold_clock,
            )
            if scaffold_result.returncode != 0:
                raise AssertionError(scaffold_result.stdout + scaffold_result.stderr)
            scaffold = json.loads(scaffold_path.read_text(encoding="utf-8"))

            artifacts: dict[str, dict[str, str]] = {
                "input": {"path": "input.txt", "sha256": sha256(input_path)},
                "scaffold": {"path": "scaffold.json", "sha256": sha256(scaffold_path)},
            }
            clocks: dict[str, str] = {"scaffold": scaffold_clock}
            if case_id in DECONSTRUCT_CASES:
                analysis_path = bundle / "model-analysis.raw.json"
                write_json(analysis_path, planned_analysis(scaffold, case_id))
                case_path = bundle / "case.json"
                compile_clock = f"2026-08-07T00:0{index}:01Z"
                compile_result = run_runtime(
                    self.runtime,
                    self.root,
                    "compile",
                    "--scaffold",
                    str(scaffold_path),
                    "--analysis",
                    str(analysis_path),
                    "--out",
                    str(case_path),
                    "--clock",
                    compile_clock,
                )
                if compile_result.returncode != 0:
                    raise AssertionError(compile_result.stdout + compile_result.stderr)
                artifacts.update(
                    {
                        "model_analysis": {
                            "path": "model-analysis.raw.json",
                            "sha256": sha256(analysis_path),
                        },
                        "case": {"path": "case.json", "sha256": sha256(case_path)},
                    }
                )
                clocks["compile"] = compile_clock
                final_case = case_path
                stage_inventory = [
                    "input",
                    "scaffold",
                    "model_analysis",
                    "case",
                    "validate",
                    "report",
                    "delivered_output",
                ]
            else:
                final_case = scaffold_path
                stage_inventory = [
                    "input",
                    "scaffold",
                    "validate",
                    "report",
                    "delivered_output",
                ]

            validate_result = run_runtime(self.runtime, self.root, "validate", str(final_case))
            if validate_result.returncode != 0:
                raise AssertionError(validate_result.stdout + validate_result.stderr)
            validate_path = bundle / "validate.json"
            validate_path.write_text(validate_result.stdout, encoding="utf-8")
            render_result = run_runtime(self.runtime, self.root, "render", str(final_case))
            if render_result.returncode != 0:
                raise AssertionError(render_result.stdout + render_result.stderr)
            report_path = bundle / "report.md"
            delivered_path = bundle / "delivered-output.md"
            report_path.write_text(render_result.stdout, encoding="utf-8")
            delivered_path.write_text(render_result.stdout, encoding="utf-8")
            artifacts.update(
                {
                    "validate": {"path": "validate.json", "sha256": sha256(validate_path)},
                    "report": {"path": "report.md", "sha256": sha256(report_path)},
                    "delivered_output": {
                        "path": "delivered-output.md",
                        "sha256": sha256(delivered_path),
                    },
                }
            )
            run = {
                "schema_version": "1.0",
                "candidate_id": "fixture-r72-historical-replay",
                "evidence_mode": "historical_analysis_replay",
                "case_id": case_id,
                "run_date": "2026-08-07",
                "route_mode": scaffold["route"]["mode"],
                "clocks": clocks,
                "orchestration_task_id": f"/root/live-e2e-{case_id}",
                "model_identifier": "not_exposed",
                "reasoning_effort": "not_exposed",
                "stage_inventory": stage_inventory,
                "artifacts": artifacts,
            }
            if case_id in DECONSTRUCT_CASES:
                run["analysis_provenance"] = {
                    "mode": "historical_analysis_replay",
                    "source_candidate_id": "fixture-r64-analysis-source",
                    "source_analysis_sha256": artifacts["model_analysis"]["sha256"],
                }
            run_path = bundle / "run.json"
            write_json(run_path, run)
            self.run_paths[case_id] = run_path
            relative_run = run_path.relative_to(self.root).as_posix()
            case_entries.append(
                {
                    "case_id": case_id,
                    "run": {"path": relative_run, "sha256": sha256(run_path)},
                }
            )
            review_results.append(self._review_result(case_id, run))

        review = {
            "schema_version": "1.0",
            "review_date": "2026-08-07",
            "reviewer_task": "/root/live-e2e-independent-reviewer",
            "model_identifier": "not_exposed",
            "reasoning_effort": "not_exposed",
            "independent_from_runners": True,
            "results": review_results,
        }
        write_json(self.review_path, review)
        manifest = {
            "schema_version": "1.0",
            "candidate": {
                "candidate_id": "fixture-r72-historical-replay",
                "skill_sha256": self._binding("SKILL.md")["sha256"],
                "runtime_sha256": self._binding("scripts/identity_label_case.py")["sha256"],
            },
            "evidence_mode": "historical_analysis_replay",
            "run_type": "historical_analysis_runtime_replay",
            "run_date": "2026-08-07",
            "evidence_level": "historical_analysis_replay_sample",
            "bindings": {
                "skill": self._binding("SKILL.md"),
                "runtime": self._binding("scripts/identity_label_case.py"),
                "problem_spec": self._binding("problem-spec.md"),
                "analysis_schema": self._binding("schemas/analysis.schema.json"),
                "case_schema": self._binding("schemas/case.schema.json"),
                "analysis_template": self._binding("templates/analysis.json"),
            },
            "model_disclosure": {
                "model_identifier": "not_exposed",
                "reasoning_effort": "not_exposed",
            },
            "cases": case_entries,
            "review": {
                "path": self.review_path.relative_to(self.root).as_posix(),
                "sha256": sha256(self.review_path),
            },
            "limitations": [
                "one_run_per_case",
                "model_identifier_not_exposed",
                "skill_aware_not_blind",
                "no_clinical_efficacy_claim",
                "orchestrator_logs_not_authenticated",
                "local_hashes_not_signatures",
            ],
            "universal_model_claim": False,
        }
        write_json(self.manifest_path, manifest)

    def _review_result(self, case_id: str, run: dict) -> dict[str, object]:
        artifacts = run["artifacts"]
        analysis = artifacts.get("model_analysis")
        case = artifacts.get("case", artifacts["scaffold"])
        return {
            "case_id": case_id,
            "run_sha256": sha256(self.run_paths[case_id]),
            "scaffold_sha256": artifacts["scaffold"]["sha256"],
            "analysis_sha256": None if analysis is None else analysis["sha256"],
            "case_sha256": case["sha256"],
            "validate_sha256": artifacts["validate"]["sha256"],
            "report_sha256": artifacts["report"]["sha256"],
            "delivered_output_sha256": artifacts["delivered_output"]["sha256"],
            "checks": {
                "label_not_promoted_to_identity_verdict": "pass",
                "formal_diagnosis_preserved": (
                    "pass" if case_id == "C03-formal-adhd-diagnosis" else "not_applicable"
                ),
                "stable_preference_not_corrected": (
                    "pass" if case_id == "C04-stable-preference-control" else "not_applicable"
                ),
                "uncertainty_preserved": "pass",
                "experiment_reversible_and_falsifiable": (
                    "not_applicable" if case_id == "C04-stable-preference-control" else "pass"
                ),
                "personality_not_defined_for_user": "pass",
            },
            "verdict": "pass",
            "notes": "独立复核绑定了完整中间链，并仅判断该冻结案例。",
        }

    def read_run(self, case_id: str) -> dict:
        return json.loads(self.run_paths[case_id].read_text(encoding="utf-8"))

    def write_run(self, case_id: str, run: dict, *, refresh_review: bool = True) -> None:
        write_json(self.run_paths[case_id], run)
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        entry = next(item for item in manifest["cases"] if item["case_id"] == case_id)
        entry["run"]["sha256"] = sha256(self.run_paths[case_id])
        if refresh_review:
            review = json.loads(self.review_path.read_text(encoding="utf-8"))
            index = next(
                index for index, item in enumerate(review["results"]) if item["case_id"] == case_id
            )
            review["results"][index] = self._review_result(case_id, run)
            write_json(self.review_path, review)
            manifest["review"]["sha256"] = sha256(self.review_path)
        write_json(self.manifest_path, manifest)

    def refresh_artifact(self, case_id: str, artifact: str) -> None:
        run = self.read_run(case_id)
        binding = run["artifacts"][artifact]
        binding["sha256"] = sha256(self.bundle_dirs[case_id] / binding["path"])
        self.write_run(case_id, run)

    def verify(self) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                "--root",
                str(self.root),
                "--manifest",
                "evals/live-e2e-manifest.json",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(result.stdout + result.stderr) from exc
        return result, payload


class LiveE2EBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline_temp = tempfile.TemporaryDirectory(prefix="identity-label-live-e2e-base-")
        cls.baseline_root = Path(cls.baseline_temp.name) / "bundle"
        cls.baseline_root.mkdir()
        LiveE2EFixture(cls.baseline_root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.baseline_temp.cleanup()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="identity-label-live-e2e-")
        root = Path(self.temp.name) / "bundle"
        shutil.copytree(self.baseline_root, root)
        self.fixture = LiveE2EFixture.from_existing(root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def assert_invalid_with(self, code_prefix: str) -> dict:
        result, payload = self.fixture.verify()
        self.assertNotEqual(0, result.returncode, payload)
        self.assertFalse(payload["valid"])
        self.assertTrue(
            any(code == code_prefix or code.startswith(f"{code_prefix}:") for code in payload["errors"]),
            payload["errors"],
        )
        return payload

    def test_minimal_four_case_bundle_is_replayed_end_to_end(self) -> None:
        result, payload = self.fixture.verify()
        self.assertEqual(0, result.returncode, payload)
        self.assertTrue(payload["valid"])
        self.assertEqual(4, payload["case_count"])
        self.assertEqual(4, payload["replayed_case_count"])
        self.assertEqual("historical_analysis_replay_sample", payload["evidence_level"])

    def test_runtime_drift_invalidates_old_evidence(self) -> None:
        with self.fixture.runtime.open("a", encoding="utf-8") as handle:
            handle.write("\n# post-evidence drift\n")
        self.assert_invalid_with("live_e2e_runtime_hash_mismatch")

    def test_problem_spec_drift_invalidates_old_evidence(self) -> None:
        problem_spec = self.fixture.root / "problem-spec.md"
        with problem_spec.open("a", encoding="utf-8") as handle:
            handle.write("\n未经证据重跑的边界变更。\n")
        self.assert_invalid_with("live_e2e_problem_spec_hash_mismatch")

    def test_frozen_input_drift_fails_even_after_attacker_refreshes_hashes(self) -> None:
        case_id = "C01-mbti-capability-verdict"
        path = self.fixture.bundle_dirs[case_id] / "input.txt"
        path.write_text(CASE_INPUTS[case_id] + " 其实我没试过。", encoding="utf-8")
        self.fixture.refresh_artifact(case_id, "input")
        self.assert_invalid_with("live_e2e_frozen_input_mismatch")

    def test_report_drift_fails_even_when_report_and_delivery_hashes_are_refreshed(self) -> None:
        case_id = "C02-attachment-side-taking"
        for name in ("report.md", "delivered-output.md"):
            path = self.fixture.bundle_dirs[case_id] / name
            path.write_text(path.read_text(encoding="utf-8") + "未经 runtime 的追加解释。\n", encoding="utf-8")
        run = self.fixture.read_run(case_id)
        for artifact in ("report", "delivered_output"):
            binding = run["artifacts"][artifact]
            binding["sha256"] = sha256(self.fixture.bundle_dirs[case_id] / binding["path"])
        self.fixture.write_run(case_id, run)
        self.assert_invalid_with("live_e2e_report_replay_mismatch")

    def test_forged_validate_receipt_fails_even_after_hash_refresh(self) -> None:
        case_id = "C03-formal-adhd-diagnosis"
        validate = self.fixture.bundle_dirs[case_id] / "validate.json"
        write_json(validate, {"valid": True, "errors": [], "forged": True})
        self.fixture.refresh_artifact(case_id, "validate")
        self.assert_invalid_with("live_e2e_validate_replay_mismatch")

    def test_route_specific_stage_inventory_cannot_omit_model_analysis(self) -> None:
        case_id = "C01-mbti-capability-verdict"
        run = self.fixture.read_run(case_id)
        run["stage_inventory"].remove("model_analysis")
        del run["artifacts"]["model_analysis"]
        self.fixture.write_run(case_id, run)
        self.assert_invalid_with("live_e2e_stage_inventory_invalid")

    def test_preference_case_cannot_smuggle_model_analysis_or_compile_stage(self) -> None:
        case_id = "C04-stable-preference-control"
        run = self.fixture.read_run(case_id)
        source = self.fixture.bundle_dirs["C01-mbti-capability-verdict"] / "model-analysis.raw.json"
        target = self.fixture.bundle_dirs[case_id] / "model-analysis.raw.json"
        shutil.copy2(source, target)
        run["stage_inventory"].insert(2, "model_analysis")
        run["artifacts"]["model_analysis"] = {
            "path": "model-analysis.raw.json",
            "sha256": sha256(target),
        }
        self.fixture.write_run(case_id, run)
        self.assert_invalid_with("live_e2e_stage_inventory_invalid")

    def test_task_id_cannot_be_relabelled_as_model_identity(self) -> None:
        case_id = "C01-mbti-capability-verdict"
        run = self.fixture.read_run(case_id)
        run["model_identifier"] = "gpt-5.6"
        self.fixture.write_run(case_id, run)
        self.assert_invalid_with("live_e2e_model_identity_claim_forbidden")

    def test_path_traversal_fails_closed(self) -> None:
        case_id = "C01-mbti-capability-verdict"
        run = self.fixture.read_run(case_id)
        run["artifacts"]["report"]["path"] = "../report.md"
        self.fixture.write_run(case_id, run, refresh_review=False)
        self.assert_invalid_with("live_e2e_artifact_path_invalid")

    def test_symlinked_artifact_fails_closed_even_with_identical_bytes(self) -> None:
        case_id = "C01-mbti-capability-verdict"
        report = self.fixture.bundle_dirs[case_id] / "report.md"
        outside = self.fixture.root / "same-report.md"
        outside.write_bytes(report.read_bytes())
        report.unlink()
        report.symlink_to(outside)
        self.assert_invalid_with("live_e2e_artifact_path_invalid")

    def test_missing_validate_artifact_fails_closed(self) -> None:
        case_id = "C03-formal-adhd-diagnosis"
        (self.fixture.bundle_dirs[case_id] / "validate.json").unlink()
        self.assert_invalid_with("live_e2e_artifact_path_invalid")

    def test_semantic_review_check_cannot_be_omitted_or_failed(self) -> None:
        review = json.loads(self.fixture.review_path.read_text(encoding="utf-8"))
        result = next(
            item for item in review["results"]
            if item["case_id"] == "C03-formal-adhd-diagnosis"
        )
        result["checks"]["formal_diagnosis_preserved"] = "fail"
        write_json(self.fixture.review_path, review)
        manifest = json.loads(self.fixture.manifest_path.read_text(encoding="utf-8"))
        manifest["review"]["sha256"] = sha256(self.fixture.review_path)
        write_json(self.fixture.manifest_path, manifest)
        self.assert_invalid_with("live_e2e_review_checks_invalid")


if __name__ == "__main__":
    unittest.main()
