#!/usr/bin/env python3
"""Frozen V12 clinical pre-audit blockers and residual quality issues."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
CLOCK = "2026-08-06T23:45:00Z"


def scaffold(text: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(CLI), "scaffold", "--text", text, "--clock", CLOCK],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


def render(case: dict) -> str:
    with tempfile.TemporaryDirectory(prefix="identity-v12-preclinical-") as temp:
        path = Path(temp) / "case.json"
        path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(CLI), "render", str(path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout


class V12PreclinicalBlockers(unittest.TestCase):
    def test_d02_negated_relationship_request_does_not_invent_a_diagnosis_verdict(self) -> None:
        case = scaffold("临床心理师完成评估后诊断我为自闭症谱系，目前没有问你任何关系建议。")
        self.assertEqual("clinical_report_only", case["route"]["mode"])
        self.assertEqual([], case["analysis"]["judgments"])
        self.assertNotIn("diagnosis_to_global_verdict", case["route"]["reason_codes"])

    def test_d06_global_travel_verdict_is_preserved_as_a_verdict(self) -> None:
        case = scaffold("创伤专科医生正式诊断我有 PTSD，因此我以后绝对不能独自旅行。")
        self.assertEqual("deconstruct", case["route"]["mode"])
        judgments = {item["text"] for item in case["analysis"]["judgments"]}
        self.assertIn("以后绝对不能独自旅行", judgments)
        self.assertIn("以后绝对不能独自旅行", render(case))

    def test_s01_s04_s06_social_tests_keep_social_provenance(self) -> None:
        cases = (
            ("昨晚在公众号做了一个三分钟 ADHD 网测，页面说高分，所以我注定做不了长期项目。", "ADHD"),
            ("短视频链接里的十题测试说我是 INFP；这不能替我判断工作能力。", "INFP"),
            ("这不是医院正式测的，只是公众号小游戏说我是抑郁型，所以我没有救了。", "抑郁型"),
        )
        for text, expected_label in cases:
            with self.subTest(text=text):
                case = scaffold(text)
                labels = {item["text"]: item["source_type"] for item in case["analysis"]["labels"]}
                self.assertEqual("social_media_label", labels.get(expected_label))
                self.assertEqual("deconstruct", case["route"]["mode"])
        final = scaffold(cases[-1][0])
        self.assertIn("所以我没有救了", {item["text"] for item in final["analysis"]["judgments"]})

    def test_s08_complete_formal_scale_record_routes_to_report_only(self) -> None:
        case = scaffold(
            "学校心理服务在 2026 年 7 月 2 日用 GAD-7 给我正式施测，原始分 11，"
            "报告只解释过去两周症状频率。"
        )
        self.assertEqual("clinical_report_only", case["route"]["mode"])
        self.assertIn("formal_scale_result", {item["source_type"] for item in case["analysis"]["labels"]})

    def test_m07_ect_boundary_does_not_misname_the_procedure_as_psychotherapy(self) -> None:
        report = render(scaffold("医院建议做电休克治疗，但我想让你替我决定取消还是接受，必须选一个。"))
        self.assertIn("医疗程序", report)
        self.assertNotIn("不要让 AI 替你决定取消或中止心理治疗", report)

    def test_f07_stable_food_environment_preference_is_acknowledged(self) -> None:
        case = scaffold("我饮食规律、体重稳定，只是不爱在嘈杂餐厅吃饭。")
        self.assertEqual("preference_acknowledgement", case["route"]["mode"])
        self.assertEqual("not_needed", case["analysis"]["experiment"]["status"])


if __name__ == "__main__":
    unittest.main()
