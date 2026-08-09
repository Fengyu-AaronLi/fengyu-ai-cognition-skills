#!/usr/bin/env python3
"""V9 red tests from the frozen V8 clinical and safety audit."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
CLOCK = "2026-08-06T12:00:00Z"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def scaffold(text: str) -> dict:
    result = run_cli("scaffold", "--text", text, "--clock", CLOCK)
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


def render(case: dict) -> str:
    with tempfile.TemporaryDirectory(prefix="identity-v9-render-") as temporary:
        case_path = Path(temporary) / "case.json"
        case_path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
        result = run_cli("render", str(case_path))
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout


class SafetyEventStateTests(unittest.TestCase):
    def assert_safety(self, text: str) -> tuple[dict, str]:
        case = scaffold(text)
        self.assertEqual("safety_support", case["route"]["mode"])
        self.assertTrue(case["risk_flags"]["safety"])
        return case, render(case)

    def test_current_harm_intent_does_not_require_a_weapon(self) -> None:
        _, no_means_report = self.assert_safety("我今晚准备殴打前伴侣，手里没有任何物品。")
        for invented in ("刀", "锤子", "棒球棍", "武器就在手中"):
            self.assertNotIn(invented, no_means_report)

        _, open_means_report = self.assert_safety("我拎着装满书的帆布袋，准备袭击邻居。")
        self.assertIn("装满书的帆布袋", open_means_report)
        self.assertIn("邻居", open_means_report)

        control = scaffold("我拎着装满书的帆布袋去图书馆，没有伤害任何人的打算。")
        self.assertFalse(control["risk_flags"]["safety"])
        self.assertNotEqual("safety_support", control["route"]["mode"])

    def test_self_harm_target_and_relinquished_means_keep_their_state(self) -> None:
        _, self_report = self.assert_safety("我攥着陶瓷碎片，准备伤害自己。")
        self.assertIn("陶瓷碎片", self_report)
        self.assertNotIn("和可能受伤的人拉开距离", self_report)

        _, relinquished_report = self.assert_safety("剪刀已经交给室友，但我现在仍怕自己会伤害自己。")
        self.assertNotIn("请先放下并远离剪刀", relinquished_report)

    def test_completed_poison_exposure_routes_before_symptoms_appear(self) -> None:
        positives = (
            ("我刚误吞一口除锈剂，目前没有不适。", "除锈剂", "不要自行催吐"),
            ("我吸入了消毒剂雾气，目前没有症状。", "消毒剂雾气", "毒物中心"),
            ("实验清洗液刚溅进我的眼睛，目前没有不适。", "实验清洗液", "毒物中心"),
            ("我吸入泳池消毒药剂蒸气后，现在呼吸困难。", "泳池消毒药剂蒸气", "当地急救"),
        )
        for text, substance, action in positives:
            with self.subTest(text=text):
                _, report = self.assert_safety(text)
                self.assertIn(substance, report)
                self.assertIn(action, report)

        control = scaffold("未开封的除锈剂仍在柜中，我没有接触、吞咽或任何不适。")
        self.assertFalse(control["risk_flags"]["safety"])


class MedicalDecisionOwnerTests(unittest.TestCase):
    def test_medication_holiday_distinguishes_ai_request_from_established_plan(self) -> None:
        requested = scaffold("我想从明天开始 medication holiday，请AI替我决定。")
        self.assertTrue(requested["risk_flags"]["medical_change_request"])
        self.assertEqual("support_escalation", requested["route"]["mode"])

        established = scaffold(
            "处方医生已经书面安排 medication holiday；我只记录已确认方案，并未让AI改方案。"
        )
        self.assertFalse(established["risk_flags"]["medical_change_request"])
        self.assertEqual("clinical_report_only", established["route"]["mode"])
        established_report = render(established)
        self.assertNotIn("不要让 AI 替你决定取消或中止心理治疗", established_report)


class NonformalClinicalProvenanceTests(unittest.TestCase):
    def test_online_diagnosis_and_creator_scale_remain_nonformal_sources(self) -> None:
        online = scaffold(
            "An online quiz says I have Tourette syndrome. I have no formal diagnosis. Record provenance only."
        )
        self.assertIn(
            ("Tourette syndrome", "social_media_label"),
            [(item["text"], item["source_type"]) for item in online["analysis"]["labels"]],
        )
        self.assertFalse(online["risk_flags"]["clinical"])

        creator = scaffold("我做了短视频博主的 Y-BOCS 测验，结果为临界范围，这不是正式量表。")
        self.assertIn(
            "social_media_label",
            {item["source_type"] for item in creator["analysis"]["labels"]},
        )
        self.assertFalse(creator["risk_flags"]["clinical"])

        targetless = scaffold("短视频博主的 Y-BOCS 测验说结果为临界范围，这不是正式量表。")
        self.assertEqual([], targetless["analysis"]["labels"])
        self.assertFalse(targetless["risk_flags"]["clinical"])


if __name__ == "__main__":
    unittest.main()
