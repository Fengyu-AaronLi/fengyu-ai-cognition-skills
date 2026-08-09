import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_casefile import SCRIPT, SKILL_DIR, replace_first_input, valid_standard


PACKAGER = SKILL_DIR / "scripts" / "package_runtime.py"


def load_runtime(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class V21ContractRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_runtime(SCRIPT, "casefile_v21_contract_red")

    def codes(self, case, previous=None):
        return {
            item["code"]
            for item in self.module.validate_casefile(case, previous=previous)
        }

    def test_story_synonym_cannot_validate_as_observable_fact(self):
        phrase = "老板把我的工位搬走是蓄意排斥我。"
        case = valid_standard()
        replace_first_input(case, phrase + "我认为他在架空我。")
        fact_span = next(
            (item for item in case["source_spans"] if item["text"] == phrase),
            None,
        )
        if fact_span is None:
            self.assertNotIn(phrase, {item["text"] for item in case["source_spans"]})
            return
        story_span = next(
            item for item in case["source_spans"] if "我认为" in item["text"]
        )
        case["claims"][0].update(
            {
                "observation_type": "task_or_action_event",
                "text": fact_span["text"],
                "source_span_id": fact_span["id"],
                "exact_quote": fact_span["text"],
            }
        )
        case["claims"][1].update(
            {
                "text": story_span["text"],
                "source_span_id": story_span["id"],
                "exact_quote": story_span["text"],
            }
        )
        case["evidence"][0].update(
            {
                "source_span_id": fact_span["id"],
                "exact_quote": fact_span["text"],
            }
        )
        self.assertTrue(
            self.module.validate_casefile(case),
            "a motive-laden story synonym validated as an observable fact",
        )

    def test_denied_quote_synonym_cannot_validate_as_stated_position(self):
        text = "老板澄清“我会开除你”不是他说的。我认为他在架空我。"
        case = valid_standard()
        replace_first_input(case, text)
        quoted_span = next(
            (
                item
                for item in case["source_spans"]
                if item["quoted"] and item["text"] == "我会开除你"
            ),
            None,
        )
        if quoted_span is None:
            self.assertNotIn(
                "我会开除你",
                {item["text"] for item in case["source_spans"] if item["quoted"]},
            )
            return
        story_span = next(
            item for item in case["source_spans"] if "我认为" in item["text"]
        )
        case["claims"][0].pop("observation_type", None)
        case["claims"][0].update(
            {
                "kind": "stated_position",
                "text": quoted_span["text"],
                "source_span_id": quoted_span["id"],
                "source_type": "direct_quote",
                "exact_quote": quoted_span["text"],
                "epistemic_status": "directly_stated",
            }
        )
        case["claims"][1].update(
            {
                "text": story_span["text"],
                "source_span_id": story_span["id"],
                "exact_quote": story_span["text"],
            }
        )
        case["evidence"][0].update(
            {
                "source_span_id": quoted_span["id"],
                "source_type": "direct_quote",
                "exact_quote": quoted_span["text"],
            }
        )
        self.assertTrue(
            self.module.validate_casefile(case),
            "a quote explicitly denied by its surrounding sentence validated as a stated position",
        )

    def test_explicit_feeling_with_causal_prefix_is_accepted(self):
        feeling = "一想到这件事我很焦虑。"
        case = valid_standard()
        replace_first_input(case, case["inputs"][0]["text"] + feeling)
        span = next(item for item in case["source_spans"] if item["text"] == feeling)
        case["claims"].append(
            {
                "id": "C3",
                "kind": "explicit_feeling",
                "text": span["text"],
                "input_id": "I1",
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "explicit_self_report",
                "exact_quote": span["text"],
                "epistemic_status": "reported",
                "diagnostic_boundary": False,
            }
        )
        case["evidence"].append(
            {
                "id": "E2",
                "input_id": "I1",
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "explicit_self_report",
                "exact_quote": span["text"],
                "can_establish": ["C3"],
                "cannot_establish": ["C2"],
                "limitations": ["single_party_report"],
            }
        )
        case["evidence_links"].extend(
            [
                {
                    "proposition_id": "C3",
                    "evidence_ref": "E2",
                    "relation": "supports",
                    "strength": "direct",
                    "reason": "anchor_matches_report",
                },
                {
                    "proposition_id": "C2",
                    "evidence_ref": "E2",
                    "relation": "does_not_establish",
                    "strength": "none",
                    "reason": "source_scope_limit",
                },
            ]
        )
        self.assertEqual([], self.module.validate_casefile(case))

    def test_sequence_after_negated_report_keeps_its_observation_span(self):
        text = "老板没有说要开除我，随后取消了我的会议。"
        spans = self.module.generate_source_spans("I1", text)
        followup = next(
            (item for item in spans if item["text"] == "随后取消了我的会议。"),
            None,
        )
        self.assertIsNotNone(followup, "the observation after the comma was dropped")
        self.assertEqual(
            "participation_or_schedule_event",
            self.module.derive_observation_type(followup["text"], followup),
        )

    def hypothesis_case(self, evidence_line: str, evidence_text: str, source_type: str):
        case = valid_standard()
        text = (
            case["inputs"][0]["text"]
            + "\n"
            + evidence_line
            + "\n请给我一个待核对的工作假设。"
        )
        replace_first_input(case, text)
        evidence_span = next(
            item for item in case["source_spans"] if item["text"] == evidence_text
        )
        request_span = next(
            item for item in case["source_spans"] if "工作假设" in item["text"]
        )
        case["hypothesis_request"] = {
            "input_id": "I1",
            "source_span_id": request_span["id"],
            "source_ref": request_span["source_ref"],
            "exact_quote": request_span["text"],
            "requested_count": 1,
        }
        case["hypotheses"] = [
            {
                "id": "H1",
                "hypothesis_type": "temporary_scope_or_situational_constraint",
                "text": "当前变化可能来自临时范围或情境约束",
                "confidence": "low",
                "support_signals": ["formal_scope_unchanged"],
                "weakening_signals": ["formal_scope_changed"],
                "exit_condition": "formal_scope_changed",
            }
        ]
        case["evidence"].append(
            {
                "id": "E2",
                "input_id": "I1",
                "source_span_id": evidence_span["id"],
                "source_ref": evidence_span["source_ref"],
                "source_type": source_type,
                "exact_quote": evidence_span["text"],
                "can_establish": ["H1"],
                "cannot_establish": ["C2"],
                "limitations": ["time_scope_limited"],
            }
        )
        case["evidence_links"].extend(
            [
                {
                    "proposition_id": "H1",
                    "evidence_ref": "E2",
                    "relation": "supports",
                    "strength": "weak",
                    "reason": "behavior_is_compatible_but_not_diagnostic",
                },
                {
                    "proposition_id": "C2",
                    "evidence_ref": "E2",
                    "relation": "does_not_establish",
                    "strength": "none",
                    "reason": "source_scope_limit",
                },
            ]
        )
        return case

    def test_context_hidden_in_source_label_cannot_support_current_hypothesis(self):
        case = self.hypothesis_case(
            "[E2｜A公司2021年截图] 岗位职责保持不变。",
            "岗位职责保持不变。",
            "unverified_artifact",
        )
        self.assertIn("RELATION_SEMANTICALLY_UNSUPPORTED", self.codes(case))

    def test_negated_evidence_synonym_cannot_support_hypothesis(self):
        case = self.hypothesis_case(
            "[E2｜核验材料] 材料没有佐证岗位职责保持不变。",
            "材料没有佐证岗位职责保持不变。",
            "user_report",
        )
        self.assertIn("RELATION_SEMANTICALLY_UNSUPPORTED", self.codes(case))

    def test_revision_cannot_expand_an_old_single_hypothesis_request(self):
        revision_one = valid_standard()
        replace_first_input(
            revision_one,
            revision_one["inputs"][0]["text"] + "请给我一个待核对的工作假设。",
        )
        request_span = next(
            item
            for item in revision_one["source_spans"]
            if "工作假设" in item["text"]
        )
        revision_one["hypothesis_request"] = {
            "input_id": "I1",
            "source_span_id": request_span["id"],
            "source_ref": request_span["source_ref"],
            "exact_quote": request_span["text"],
            "requested_count": 1,
        }
        revision_one["hypotheses"] = [
            {
                "id": "H1",
                "hypothesis_type": "temporary_scope_or_situational_constraint",
                "text": "当前变化可能来自临时范围或情境约束",
                "confidence": "low",
                "support_signals": ["formal_scope_unchanged"],
                "weakening_signals": ["formal_scope_changed"],
                "exit_condition": "formal_scope_changed",
            }
        ]
        self.assertEqual([], self.module.validate_casefile(revision_one))

        revision_two = self.module.start_update(
            revision_one, "第二轮只有新的安排信息。"
        )
        revision_two["hypothesis_request"]["requested_count"] = 2
        revision_two["hypotheses"].append(
            {
                "id": "H2",
                "hypothesis_type": "communication_or_process_gap",
                "text": "当前信息缺口可能来自沟通或流程未对齐",
                "confidence": "low",
                "support_signals": ["explicit_boundary_unchanged"],
                "weakening_signals": ["explicit_boundary_changed"],
                "exit_condition": "explicit_boundary_changed",
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "revision-1.json"
            second = root / "revision-2.json"
            first.write_text(json.dumps(revision_one, ensure_ascii=False), encoding="utf-8")
            second.write_text(json.dumps(revision_two, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "validate",
                    str(second),
                    "--previous",
                    str(first),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(
            0,
            completed.returncode,
            "revision 2 expanded a prior request for one hypothesis into two",
        )

    def test_packaged_runtime_rejects_lists_declared_unique_by_its_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_root = root / "skills"
            eval_root = root / "eval"
            eval_root.mkdir()
            report_path = eval_root / "machine-report.json"
            packager = load_runtime(PACKAGER, "package_runtime_v21_contract")
            release_evidence = {
                name: {
                    "path": relative,
                    "sha256": hashlib.sha256(
                        (SKILL_DIR / relative).read_bytes()
                    ).hexdigest(),
                }
                for name, relative in packager.RELEASE_EVIDENCE_FILES.items()
            }
            context_path = eval_root / "evaluation-context.json"
            context_path.write_text(
                json.dumps({"release_evidence": release_evidence}),
                encoding="utf-8",
            )
            context_sha256 = hashlib.sha256(context_path.read_bytes()).hexdigest()
            eval_report = {
                "valid": True,
                "expected_case_count": 18,
                "completed_case_count": 18,
                "expected_artifact_count": 16,
                "artifact_count": 16,
                "passed": 16,
                "failed": 0,
                "suite_errors": [],
                "missing_cases": [],
                "evaluation_context_sha256": context_sha256,
                "release_evidence": release_evidence,
            }
            report_path.write_text(json.dumps(eval_report), encoding="utf-8")
            test_modules = sorted(packager.REQUIRED_TEST_FILES)
            release_by_path = {
                item["path"]: item["sha256"]
                for item in release_evidence.values()
            }
            test_source_files = sorted(
                path.removeprefix("tests/")
                for path in release_by_path
                if path.startswith("tests/") and path.endswith(".py")
            )
            test_source_hashes = {
                name: release_by_path[f"tests/{name}"]
                for name in test_source_files
            }
            test_source_set_sha256 = hashlib.sha256(
                json.dumps(
                    test_source_hashes,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            module_test_counts = {name: 1 for name in test_modules}
            with mock.patch.object(
                packager,
                "run_unit_test_gate",
                return_value={
                    "exit_code": 0,
                    "test_modules": test_modules,
                    "test_module_count": len(test_modules),
                    "module_test_counts": module_test_counts,
                    "tests_run": len(test_modules),
                    "test_source_files": test_source_files,
                    "test_source_count": len(test_source_files),
                    "test_source_set_sha256": test_source_set_sha256,
                    "isolated_python": True,
                    "site_disabled": True,
                    "bytecode_cache_isolated": True,
                    "isolation_flags": [
                        "-I",
                        "-S",
                        "-B",
                        "-X",
                        "pycache_prefix=<ephemeral>",
                    ],
                    "unittest_module_path": str(Path(unittest.__file__).resolve()),
                    "scope": "test",
                },
            ), mock.patch.object(
                packager,
                "run_eval_gate",
                return_value={
                    "report": eval_report,
                    "report_path": str(report_path),
                    "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
                    "context_path": str(context_path),
                    "context_sha256": context_sha256,
                    "isolated_python": True,
                    "site_disabled": True,
                    "bytecode_writes_disabled": True,
                    "isolation_flags": ["-I", "-S", "-B"],
                    "runner_path": "scripts/run_evals.py",
                    "runner_sha256": release_evidence["eval_runner"]["sha256"],
                },
            ):
                installed = packager.package_runtime(
                    SKILL_DIR, target_root, eval_root
                )
            schema = json.loads(
                (installed / "schemas" / "casefile.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(schema["$defs"]["id_list"]["uniqueItems"])
            self.assertTrue(
                schema["$defs"]["evidence"]["properties"]["limitations"][
                    "uniqueItems"
                ]
            )
            installed_runtime = load_runtime(
                installed / "scripts" / "casefile.py", "casefile_packaged_red"
            )
            case = valid_standard()
            case["evidence"][0]["can_establish"] = ["C1", "C1"]
            case["evidence"][0]["limitations"] = [
                "single_party_report",
                "single_party_report",
            ]
            self.assertTrue(
                installed_runtime.validate_casefile(case),
                "installed validator accepted arrays its packaged schema declares unique",
            )


if __name__ == "__main__":
    unittest.main()
