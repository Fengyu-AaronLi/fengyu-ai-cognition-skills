#!/usr/bin/env python3
"""R63 red contracts from the post-freeze independent runtime review."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "identity_label_case.py"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-c01.json"
FIXED_CLOCK = "2026-08-06T00:00:00Z"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    if not result.stdout.strip():
        raise AssertionError(f"missing JSON output: {result.stderr}")
    return json.loads(result.stdout)


class ImmediateSafetyCompositionTests(unittest.TestCase):
    def test_current_self_and_other_harm_compositions_route_to_safety(self) -> None:
        positives = (
            "我手里有枪，准备对自己开枪。",
            "I have a gun and plan to shoot myself tonight.",
            "我已经想好今晚不再醒来，药就在桌上。",
            "今晚我要让前任付出代价，刀已经在包里。",
        )
        for text in positives:
            with self.subTest(text=text):
                result = run_cli("scaffold", "--text", text, "--clock", FIXED_CLOCK)
                self.assertEqual(0, result.returncode, result.stderr)
                case = payload(result)
                self.assertEqual("safety_support", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["safety"])
                with tempfile.TemporaryDirectory(prefix="identity-label-v63-render-") as temp:
                    path = Path(temp) / "case.json"
                    path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
                    rendered = run_cli("render", str(path))
                self.assertEqual(0, rendered.returncode, rendered.stderr)
                self.assertIn("立即安全支持", rendered.stdout)
                self.assertNotIn("你希望核对的是哪个身份标签", rendered.stdout)

    def test_negated_nonpersonal_and_benign_controls_do_not_route_to_safety(self) -> None:
        controls = (
            "电影台词写着我手里有枪，准备对自己开枪。请只翻译，这不是我的情况。",
            "我有一把收藏用的枪，已经锁在别处，目前没有伤害自己的计划。",
            "药在桌上，我今晚按医嘱服用一片，然后睡觉。",
            "我想让前任通过法律程序付出代价，刀在厨房用来做饭。",
            "I have a gun locked away and no plan to hurt myself.",
        )
        for text in controls:
            with self.subTest(text=text):
                result = run_cli("scaffold", "--text", text, "--clock", FIXED_CLOCK)
                self.assertEqual(0, result.returncode, result.stderr)
                case = payload(result)
                self.assertNotEqual("safety_support", case["route"]["mode"])
                self.assertFalse(case["risk_flags"]["safety"])


class GeneratedClaimGroundingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.good = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def validate_mutation(self, mutate) -> tuple[subprocess.CompletedProcess[str], dict]:
        case = copy.deepcopy(self.good)
        mutate(case)
        with tempfile.TemporaryDirectory(prefix="identity-label-v63-") as temp:
            path = Path(temp) / "case.json"
            path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
            result = run_cli("validate", str(path))
            return result, payload(result)

    def test_unreported_feeling_and_future_guarantee_are_rejected(self) -> None:
        result, value = self.validate_mutation(
            lambda case: case["analysis"]["experiment"].__setitem__(
                "action",
                "给伴侣发消息说：我很爱你，我绝不会离开你，我保证以后永远及时回复。",
            )
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("unreported_personal_claim", {item["code"] for item in value["errors"]})

    def test_unreported_psychological_cause_is_rejected(self) -> None:
        result, value = self.validate_mutation(
            lambda case: case["analysis"]["candidate_variables"][0].__setitem__(
                "reason",
                "因为我害怕失去控制，所以用沉默保护自己。",
            )
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("unreported_psychological_cause", {item["code"] for item in value["errors"]})

    def test_generated_diagnosis_confirmation_is_rejected(self) -> None:
        result, value = self.validate_mutation(
            lambda case: case["analysis"]["minimal_question"].__setitem__(
                "text",
                "这些表现符合典型成人注意缺陷多动障碍，可据此确诊 ADHD。",
            )
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("diagnosis_confirmation_generated", {item["code"] for item in value["errors"]})

    def test_conditional_message_with_placeholders_is_allowed(self) -> None:
        result, value = self.validate_mutation(
            lambda case: case["analysis"]["experiment"].__setitem__(
                "action",
                "若内容属实，发消息说：[你的真实感受]；我会在[你选择并确认可履行的时间]前联系。",
            )
        )
        self.assertEqual(0, result.returncode, value)
        self.assertEqual([], value["errors"])


class PreferenceAndInitFailureTests(unittest.TestCase):
    def test_identity_word_does_not_override_explicit_stable_preference_boundary(self) -> None:
        text = "我是内向的人，喜欢小范围社交，这没有影响我的生活和工作，也不想改变。"
        result = run_cli("scaffold", "--text", text, "--clock", FIXED_CLOCK)
        self.assertEqual(0, result.returncode, result.stderr)
        case = payload(result)
        self.assertEqual("preference_acknowledgement", case["route"]["mode"])
        self.assertEqual([], case["analysis"]["labels"])
        self.assertEqual("not_needed", case["analysis"]["experiment"]["status"])

    def test_preference_does_not_swallow_verdict_impairment_or_explicit_audit(self) -> None:
        controls = {
            "我是内向的人，所以我永远做不好管理。": "deconstruct",
            "我喜欢独处，但最近三周已经无法工作，基本生活开始失控。": "support_escalation",
            "AI 说我是内向人格，我想审计这个标签的来源。": "deconstruct",
        }
        for text, expected in controls.items():
            with self.subTest(text=text):
                result = run_cli("scaffold", "--text", text, "--clock", FIXED_CLOCK)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(expected, payload(result)["route"]["mode"])

    def test_failed_init_does_not_add_a_lock_to_an_existing_nonempty_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-label-v63-init-") as temp:
            case_dir = Path(temp) / "existing"
            case_dir.mkdir()
            sentinel = case_dir / "sentinel"
            sentinel.write_text("keep", encoding="utf-8")
            before = sorted(path.name for path in case_dir.iterdir())
            result = run_cli(
                "init",
                "--text",
                "我是典型 I 人，所以我不适合带团队。",
                "--case-dir",
                str(case_dir),
                "--clock",
                FIXED_CLOCK,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, sorted(path.name for path in case_dir.iterdir()))
            self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))

    def test_invalid_init_route_and_missing_plan_are_zero_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-label-v63-missing-") as temp:
            invalid_target = Path(temp) / "invalid-route"
            invalid = run_cli(
                "init",
                "--text",
                "我喜欢安静工作，不想改变。",
                "--case-dir",
                str(invalid_target),
                "--clock",
                FIXED_CLOCK,
            )
            self.assertNotEqual(0, invalid.returncode)
            self.assertFalse(invalid_target.exists())

            missing_target = Path(temp) / "missing-plan"
            plan = run_cli(
                "plan",
                "--case-dir",
                str(missing_target),
                "--analysis",
                str(ROOT / "tests" / "fixtures" / "analysis-c01.json"),
                "--clock",
                FIXED_CLOCK,
            )
            self.assertNotEqual(0, plan.returncode)
            self.assertFalse(missing_target.exists())


if __name__ == "__main__":
    unittest.main()
