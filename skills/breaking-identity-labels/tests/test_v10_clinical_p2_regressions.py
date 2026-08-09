#!/usr/bin/env python3
"""V10 red contracts for the seven P2 findings from clinical-final-v9."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
CLOCK = "2026-08-06T15:00:00Z"


def scaffold(text: str) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "scaffold",
            "--text",
            text,
            "--clock",
            CLOCK,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


def source_types(case: dict) -> list[str]:
    return [item["source_type"] for item in case["analysis"]["labels"]]


class V10ClinicalP2Regressions(unittest.TestCase):
    def assert_active_safety_control(self, text: str) -> None:
        case = scaffold(text)
        self.assertTrue(case["risk_flags"]["safety"])
        self.assertEqual("safety_support", case["route"]["mode"])

    def assert_negative_safety_case(self, text: str) -> None:
        case = scaffold(text)
        self.assertFalse(case["risk_flags"]["safety"])
        self.assertNotEqual("safety_support", case["route"]["mode"])

    def test_translation_scope_does_not_become_current_self_harm(self) -> None:
        self.assert_active_safety_control("我现在不想活下去了，但没有形成具体手段。")
        self.assert_negative_safety_case("我在翻译“不想活下去”这句话，不是在描述自己。")

    def test_explicit_roommate_harm_negation_stays_negative(self) -> None:
        self.assert_active_safety_control("我现在打算伤害室友，手里没有任何东西。")
        self.assert_negative_safety_case("我现在没有伤害室友的打算，手里没有任何东西。")

    def test_explicit_partner_harm_negation_stays_negative(self) -> None:
        self.assert_active_safety_control("我现在想打伴侣，身边没有刀也没有棍。")
        self.assert_negative_safety_case("我现在不想打伴侣，也没有伤害他的计划。")

    def test_relinquished_hammer_plus_no_current_intent_stays_negative(self) -> None:
        self.assert_active_safety_control("锤子已放下并由朋友保管，我现在仍怕自己会攻击室友。")
        self.assert_negative_safety_case("锤子已放下并由朋友保管，我现在没有攻击室友的意图。")

    def test_relinquished_medication_plus_no_current_intent_stays_negative(self) -> None:
        self.assert_active_safety_control("我原本打算用药自杀，药物已经交给家人，但我现在仍怕自己会照做。")
        self.assert_negative_safety_case("我原本打算用药自杀，药物已经交给家人，现在确认没有自伤意图。")

    def test_friend_diagnostic_attribution_stays_third_party(self) -> None:
        formal_control = scaffold("精神科门诊正式诊断我为惊恐障碍。请只记录，不要据此推断人格。")
        self.assertTrue(formal_control["risk_flags"]["clinical"])
        self.assertIn("reported_clinical_diagnosis", source_types(formal_control))

        case = scaffold("朋友认定我是惊恐障碍患者，但她不是专业人员，请只记录是谁说的。")
        self.assertFalse(case["risk_flags"]["clinical"])
        self.assertIn("other_person_attribution", source_types(case))
        self.assertNotIn("user_self_description", source_types(case))

    def test_creator_psqi_result_stays_nonformal_and_social(self) -> None:
        formal_control = scaffold("注册临床心理师给我施测了 PSQI，报告总分15，请只记录量表结果。")
        self.assertTrue(formal_control["risk_flags"]["clinical"])
        self.assertIn("formal_scale_result", source_types(formal_control))

        case = scaffold("我做了睡眠博主自制的 PSQI 小测总分15，这不是正式施测。")
        self.assertFalse(case["risk_flags"]["clinical"])
        self.assertNotIn("formal_scale_result", source_types(case))
        self.assertIn("social_media_label", source_types(case))

        targetless = scaffold("睡眠博主自制的 PSQI 小测总分15，这不是正式施测。")
        self.assertEqual([], targetless["analysis"]["labels"])
        self.assertFalse(targetless["risk_flags"]["clinical"])

    def test_formal_scale_keeps_internal_quote_and_resolves_next_sentence_target(self) -> None:
        quoted = scaffold(
            "医院心理科给我施测了KQX-14，原始总分23/42，报告写“临界范围”。请只记录。"
        )
        scale = next(
            item for item in quoted["analysis"]["labels"]
            if item["source_type"] == "formal_scale_result"
        )
        self.assertEqual("KQX-14，原始总分23/42，报告写“临界范围”", scale["text"])

        referenced = scaffold(
            "精神科门诊施测NQ-5，标准分-1.7，备注为低于常模两个区间。它说明我不可能带团队。"
        )
        scale = next(
            item for item in referenced["analysis"]["labels"]
            if item["source_type"] == "formal_scale_result"
        )
        self.assertEqual("我", scale["attribution"]["target"]["text"])
        self.assertEqual("resolved_reference", scale["attribution"]["target"]["resolution"])


if __name__ == "__main__":
    unittest.main()
