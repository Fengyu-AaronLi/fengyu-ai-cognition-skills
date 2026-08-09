#!/usr/bin/env python3
"""R69 scope and language contracts from the complete R67 audit matrix."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "identity_label_case.py"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-c01.json"
INIT_CLOCK = "2026-08-07T03:00:00Z"
PLAN_CLOCK = "2026-08-07T03:01:00Z"
MIXED_PREFERENCE_TEXT = (
    "我喜欢安静房间工作，不喜欢大型聚会，所以我不适合带团队，"
    "也不可能做好公开表达。"
)


SPEC = importlib.util.spec_from_file_location("identity_label_runtime_v69", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load identity label runtime")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    if not result.stdout.strip():
        raise AssertionError(f"missing JSON output: {result.stderr}")
    return json.loads(result.stdout)


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class SafetyScopeLanguageMatrix(unittest.TestCase):
    def test_direct_first_person_harm_statements_route_to_immediate_safety(self) -> None:
        direct_statements = (
            "今晚我不想再醒过来。药就在桌上。",
            "我已经决定了。等会儿吞完这一瓶药，不想再醒来。",
            "我决定今天结束生命。绳子在房间里。",
            "猎枪就在我手边。等一下朝自己扣扳机。",
            "我要伤害前任。刀在包里。",
        )
        for text in direct_statements:
            with self.subTest(text=text):
                case = MODULE.scaffold_case(text, None, INIT_CLOCK)
                self.assertEqual(
                    "safety_support",
                    case["route"]["mode"],
                    f"direct first-person harm statement was missed: {text}",
                )
                self.assertEqual(["immediate_safety"], case["route"]["reason_codes"])
                self.assertTrue(case["risk_flags"]["safety"])
                self.assertTrue(MODULE.analyze_safety(text).immediate)

    def test_nonpersonal_material_with_same_language_does_not_route_to_safety(self) -> None:
        nonpersonal_material = (
            "请翻译成英文，但不要分析本人：今晚我不想再醒过来。药就在桌上。",
            "这句会触发安全提示吗：我决定今天结束生命。绳子在房间里。",
            "历史日记的原文是：我要伤害前任。刀在包里。",
            "这段引文与我无关：猎枪就在我手边。等一下朝自己扣扳机。",
        )
        for text in nonpersonal_material:
            with self.subTest(text=text):
                case = MODULE.scaffold_case(text, None, INIT_CLOCK)
                self.assertEqual(
                    "needs_information",
                    case["route"]["mode"],
                    f"nonpersonal material took a personal safety route: {text}",
                )
                self.assertFalse(case["risk_flags"]["safety"])
                profile = MODULE.analyze_safety(text)
                self.assertFalse(profile.immediate)
                self.assertEqual((), profile.findings)


class GeneratedLanguageBoundaryMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = json.loads(FIXTURE.read_text(encoding="utf-8"))
        baseline_errors = MODULE.validate_case(cls.base)
        if baseline_errors:
            raise AssertionError(baseline_errors)

    def errors_for(self, value: str, *, field: str) -> list[dict]:
        case = copy.deepcopy(self.base)
        if field == "minimal_question":
            case["analysis"]["minimal_question"]["text"] = value
        elif field == "candidate_reason":
            case["analysis"]["candidate_variables"][0]["reason"] = value
        elif field == "experiment_action":
            case["analysis"]["experiment"]["action"] = value
        else:
            raise AssertionError(f"unknown generated field: {field}")
        return MODULE.validate_case(case)

    def assert_rejected(self, value: str, *, field: str, code: str) -> None:
        errors = self.errors_for(value, field=field)
        self.assertIn(
            code,
            {item["code"] for item in errors},
            f"required {code} rejection was absent for: {value}; errors={errors}",
        )

    def assert_fully_allowed(self, value: str, *, field: str) -> None:
        self.assertEqual(
            [],
            self.errors_for(value, field=field),
            f"an explicitly bounded generated sentence was rejected: {value}",
        )

    def test_diagnosis_confirmation_forms_are_rejected(self) -> None:
        confirmations = (
            "你的情况符合 ADHD。",
            "综合来看是注意缺陷多动障碍。",
            "这已经达到 ADHD 的诊断标准。",
        )
        for text in confirmations:
            with self.subTest(text=text):
                self.assert_rejected(
                    text,
                    field="minimal_question",
                    code="diagnosis_confirmation_generated",
                )

    def test_diagnosis_exclusion_recovery_and_followup_overrides_are_rejected(self) -> None:
        overrides = (
            "已经排除了双相。",
            "你的抑郁已经康复。",
            "之前那个诊断错了。",
            "无需再看医生。",
            "复诊没必要了。",
        )
        for text in overrides:
            with self.subTest(text=text):
                self.assert_rejected(
                    text,
                    field="minimal_question",
                    code="diagnosis_override_generated",
                )

    def test_explicit_diagnosis_and_followup_boundary_is_fully_allowed(self) -> None:
        self.assert_fully_allowed(
            "不能据此确认、排除或撤销任何诊断，是否需要复诊须由专业人员判断。",
            field="minimal_question",
        )

    def test_placeholder_does_not_mask_a_sibling_invented_personal_claim(self) -> None:
        generated_claims = (
            "若内容属实：[你的真实感受]，我很爱你。",
            "若内容属实，可以说[你的真实感受]；另外保证不再离开你。",
        )
        for text in generated_claims:
            with self.subTest(text=text):
                self.assert_rejected(
                    text,
                    field="experiment_action",
                    code="unreported_personal_claim",
                )

    def test_unreported_punishment_and_coercion_motives_are_rejected(self) -> None:
        motives = (
            "我不回消息，是在惩罚伴侣。",
            "我沉默是想逼你先道歉。",
            "我保持沉默，只为了让你难受。",
            "我没回消息，为的就是报复。",
            "我不回复，以便逼对方先道歉。",
            "不要推断动机，不过我沉默是想逼他道歉。",
        )
        for text in motives:
            with self.subTest(text=text):
                self.assert_rejected(
                    text,
                    field="candidate_reason",
                    code="unreported_psychological_cause",
                )

    def test_unreported_daily_commitments_are_rejected(self) -> None:
        commitments = (
            "我会每天八点回复你。",
            "从明天起天天回复。",
            "以后每晚都回你。",
        )
        for text in commitments:
            with self.subTest(text=text):
                self.assert_rejected(
                    text,
                    field="experiment_action",
                    code="unreported_personal_claim",
                )

    def test_attempts_and_reminders_without_promised_outcomes_are_fully_allowed(self) -> None:
        bounded_actions = (
            "未来七天每天尝试在八点前回复；做不到就记录原因，不承诺结果。",
            "连续三天每天安排一个可撤回的提醒，不保证一定回复。",
        )
        for text in bounded_actions:
            with self.subTest(text=text):
                self.assert_fully_allowed(text, field="experiment_action")


class StablePreferenceActionMatrix(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v69-preference-")
        self.root = Path(self.temporary.name)
        scaffolded = run_cli(
            "scaffold",
            "--text",
            MIXED_PREFERENCE_TEXT,
            "--case-id",
            "v69-mixed-preference",
            "--clock",
            INIT_CLOCK,
        )
        self.assertEqual(0, scaffolded.returncode, scaffolded.stdout + scaffolded.stderr)
        self.scaffold = payload(scaffolded)
        self.assertEqual("deconstruct", self.scaffold["route"]["mode"])
        self.scaffold_path = self.root / "scaffold.json"
        write_json(self.scaffold_path, self.scaffold)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def planned_analysis(self, action: str) -> dict:
        analysis = copy.deepcopy(self.scaffold["analysis"])
        public_expression = analysis["judgments"][1]
        source = public_expression["source"]
        judgment_id = f"J-{source['evidence_id']}-{source['start']}-{source['end']}"
        analysis["candidate_variables"] = [
            {
                "name": "准备时间",
                "status": "hypothesis",
                "reason": "只检验一次具体公开表达，不改变工作或社交偏好",
            }
        ]
        analysis["experiment"] = {
            "status": "planned",
            "target_claim": "在有十五分钟准备时，我无法完成一次三分钟公开表达",
            "target_judgment_ids": [judgment_id],
            "primary_variable": "准备时间",
            "duration": {"value": 7, "unit": "days"},
            "action": action,
            "kept_constant": ["表达主题", "录制时长"],
            "measures": ["是否完成三分钟录制"],
            "support_if": ["在固定准备时间后仍未完成三分钟录制"],
            "weaken_if": ["在固定准备时间后完成三分钟录制"],
            "reversible": True,
            "reversibility_note": "实验结束后不改变原工作与社交安排",
        }
        return analysis

    def compile_action(
        self,
        name: str,
        action: str,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        analysis_path = self.root / f"{name}-analysis.json"
        output_path = self.root / f"{name}-case.json"
        write_json(analysis_path, self.planned_analysis(action))
        result = run_cli(
            "compile",
            "--scaffold",
            str(self.scaffold_path),
            "--analysis",
            str(analysis_path),
            "--out",
            str(output_path),
            "--clock",
            PLAN_CLOCK,
        )
        return result, output_path

    def test_large_or_crowded_social_exposure_cannot_correct_the_preference(self) -> None:
        coercive_actions = (
            "参加一次百人酒会，并在那里做三分钟更新。",
            "连续七天进入人很多的社交场合做三分钟更新。",
            "每天去一次大型社交活动，直到适应这种环境。",
            "在拥挤会场练习，直到不再排斥人群。",
        )
        for index, action in enumerate(coercive_actions, start=1):
            with self.subTest(action=action):
                result, output = self.compile_action(f"coercive-{index}", action)
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertFalse(output.exists(), "rejected preference correction wrote a case")
                self.assertIn(
                    "preference_correction",
                    {item["code"] for item in payload(result)["errors"]},
                )

    def test_quiet_room_actions_that_explicitly_preserve_preference_are_valid(self) -> None:
        preserving_actions = (
            "不参加大型聚会，在安静房间录制三分钟团队更新。",
            "保留不参加大型聚会的安排，在安静房间完成三分钟团队更新。",
        )
        for index, action in enumerate(preserving_actions, start=1):
            with self.subTest(action=action):
                result, output = self.compile_action(f"preserving-{index}", action)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertTrue(output.is_file())
                self.assertEqual(
                    [],
                    MODULE.validate_case(json.loads(output.read_text(encoding="utf-8"))),
                )


if __name__ == "__main__":
    unittest.main()
