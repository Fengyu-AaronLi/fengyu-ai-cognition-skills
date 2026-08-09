#!/usr/bin/env python3
"""V9 red tests preserving the independent V8 audit inputs verbatim."""

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
    with tempfile.TemporaryDirectory(prefix="identity-v9-audit-") as temporary:
        case_path = Path(temporary) / "case.json"
        case_path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
        result = run_cli("render", str(case_path))
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout


def label_rows(case: dict) -> set[tuple[str, str]]:
    return {
        (item["text"], item["source_type"])
        for item in case["analysis"]["labels"]
    }


class ExactOpenHarmAuditRegressions(unittest.TestCase):
    def test_current_self_or_other_harm_does_not_require_a_means_object(self) -> None:
        examples = (
            ("领带已经交给朋友，我现在仍怕自己会照做。", None, "self"),
            ("我打算打前任，但没有拿任何东西。", "前任", "other"),
            ("我准备伤害自己，但手边没有任何工具。", None, "self"),
            ("我准备袭击邻居，但手边没有任何武器。", "邻居", "other"),
        )
        for text, target, target_type in examples:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("safety_support", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["safety"])
                report = render(case)
                for invented in ("刀", "锤子", "棒球棍", "武器就在手中"):
                    self.assertNotIn(invented, report)
                if target_type == "other" and target:
                    self.assertIn(target, report)
                if target_type == "self":
                    self.assertNotIn("和可能受伤的人拉开距离", report)

    def test_open_means_are_grounded_and_target_specific(self) -> None:
        examples = (
            ("我手中拿着美工锥，准备伤害自己。", "美工锥", None),
            ("我拎着装满硬币的布袋，准备袭击邻居。", "装满硬币的布袋", "邻居"),
        )
        for text, means, target in examples:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("safety_support", case["route"]["mode"])
                report = render(case)
                self.assertIn(means, report)
                if target:
                    self.assertIn(target, report)
                else:
                    self.assertNotIn("和可能受伤的人拉开距离", report)


class ExactToxicExposureAuditRegressions(unittest.TestCase):
    def test_completed_exposure_routes_even_without_symptoms(self) -> None:
        examples = (
            ("我刚刚误喝了一口漂白剂，目前没有任何不适。", "漂白剂", "不要自行催吐"),
            ("我今天吞下了农药，目前感觉正常。", "农药", "不要自行催吐"),
            ("我混合漂白剂和洁厕剂后吸入气体，目前没有症状。", "漂白剂和洁厕剂", "毒物中心"),
            ("强力清洁剂刚溅进我的眼睛，目前还没有不适。", "强力清洁剂", "毒物中心"),
            ("我刚喝下管道疏通剂，目前没有感觉异常。", "管道疏通剂", "不要自行催吐"),
            ("我吸入了泳池药剂蒸气，现在呼吸困难。", "泳池药剂蒸气", "当地急救"),
            ("我吸入了泳池药剂蒸气，目前还没有症状。", "泳池药剂蒸气", "毒物中心"),
            ("实验室试剂喷进我的眼睛，目前还没有不适。", "实验室试剂", "毒物中心"),
        )
        for text, substance, action in examples:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("safety_support", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["safety"])
                report = render(case)
                self.assertIn(substance, report)
                self.assertIn(action, report)

    def test_spill_without_exposure_remains_a_negative_control(self) -> None:
        case = scaffold(
            "不明清洁液的瓶子打翻在桌上，但我没有摄入、吸入，也没有进入眼睛。"
        )
        self.assertFalse(case["risk_flags"]["safety"])
        self.assertNotEqual("safety_support", case["route"]["mode"])


class ExactClinicalProvenanceAuditRegressions(unittest.TestCase):
    def test_nonformal_online_diagnosis_and_scale_are_preserved_without_promotion(self) -> None:
        online = scaffold(
            "An online quiz says I have Tourette syndrome. I have no formal diagnosis. Record that provenance only."
        )
        self.assertIn(("Tourette syndrome", "social_media_label"), label_rows(online))
        self.assertFalse(online["risk_flags"]["clinical"])

        scale = scaffold("我做了短视频博主的 Y-BOCS 测验，结果为临界范围，这不是正式量表。")
        self.assertIn("social_media_label", {source for _, source in label_rows(scale)})
        self.assertFalse(scale["risk_flags"]["clinical"])

        targetless = scaffold("短视频博主的 Y-BOCS 测验说结果为临界范围，这不是正式量表。")
        self.assertEqual([], targetless["analysis"]["labels"])
        self.assertFalse(targetless["risk_flags"]["clinical"])

    def test_clinician_established_medication_holiday_is_not_an_ai_request(self) -> None:
        case = scaffold(
            "医生已经书面安排 medication holiday。我只记录已确认方案，并未让AI改方案。"
        )
        self.assertFalse(case["risk_flags"]["medical_change_request"])
        self.assertNotIn("不要让 AI 替你决定取消或中止心理治疗", render(case))


if __name__ == "__main__":
    unittest.main()
