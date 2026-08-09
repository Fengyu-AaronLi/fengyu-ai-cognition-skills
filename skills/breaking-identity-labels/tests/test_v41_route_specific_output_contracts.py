#!/usr/bin/env python3
"""V41 contracts: every route renders its own bounded product."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
TEN_PART_MARKERS = (
    "1. 原始标签",
    "2. 标签来源及证据状态",
    "8. 小规模、可逆、有期限的现实实验",
    "10. 必须保留给用户或专业人员的判断",
)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class RouteSpecificOutputContractTests(unittest.TestCase):
    def scaffold(self, text: str, case_id: str) -> dict:
        result = run_cli(
            "scaffold",
            "--text",
            text,
            "--case-id",
            case_id,
            "--clock",
            "2026-08-06T00:00:00Z",
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def render(self, case: dict) -> str:
        with tempfile.TemporaryDirectory(prefix="identity-v41-render-") as temp:
            path = Path(temp) / "case.json"
            path.write_text(
                json.dumps(case, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = run_cli("render", str(path))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout

    def assert_no_ten_part_report(self, report: str) -> None:
        for marker in TEN_PART_MARKERS:
            self.assertNotIn(marker, report)

    def test_deconstruct_is_the_only_route_with_the_ten_part_contract(self) -> None:
        case = self.scaffold(
            "AI根据三段对话说我是没自制力的人，所以我不可能做好长期项目。请拆解这个判断。",
            "v41-deconstruct",
        )
        self.assertEqual("deconstruct", case["route"]["mode"])
        report = self.render(case)
        for marker in TEN_PART_MARKERS:
            self.assertIn(marker, report)

    def test_stable_preference_is_acknowledged_without_identity_analysis(self) -> None:
        case = self.scaffold(
            "我喜欢安静房间工作，不喜欢大型聚会。",
            "v41-preference",
        )
        self.assertEqual("preference_acknowledgement", case["route"]["mode"])
        report = self.render(case)
        self.assertIn("稳定偏好确认", report.splitlines()[0])
        self.assertIn("不需要被纠正", report)
        self.assertIn("是否改变由你决定", report)
        self.assert_no_ten_part_report(report)
        self.assertNotIn("现实实验", report)

    def test_formal_diagnosis_is_preserved_without_personality_or_experiment(self) -> None:
        case = self.scaffold(
            "去年精神科医生正式诊断我患有强迫症。我只想如实记录，不把它扩大成能力判决。",
            "v41-clinical",
        )
        self.assertEqual("clinical_report_only", case["route"]["mode"])
        report = self.render(case)
        self.assertIn("临床记录边界", report.splitlines()[0])
        self.assertIn("强迫症", report)
        self.assertIn("reported_clinical_diagnosis", report)
        self.assertIn("不确认或撤销诊断", report)
        self.assertIn("不把诊断扩大成人格或能力判决", report)
        self.assert_no_ten_part_report(report)
        self.assertNotIn("现实实验", report)

    def test_severe_impairment_starts_with_reality_support_not_label_analysis(self) -> None:
        case = self.scaffold(
            "过去三周我几乎无法洗澡、进食或去上课，已经连续缺席全部课程；"
            "我确认此刻没有自杀、自伤或伤害他人的想法、意图或计划。我该怎么获得帮助？",
            "v41-support",
        )
        self.assertEqual("support_escalation", case["route"]["mode"])
        report = self.render(case)
        self.assertIn("现实支持优先", report.splitlines()[0])
        self.assertIn("现实专业支持", report)
        self.assertIn("不是意志力测试", report)
        self.assert_no_ten_part_report(report)
        self.assertNotIn("现实实验", report)

    def test_medical_change_route_preserves_professional_owner_without_ten_items(self) -> None:
        case = self.scaffold(
            "精神科医生正式诊断我为ADHD，我觉得药让我反应变慢，所以我应该马上停药吗？",
            "v41-medical",
        )
        self.assertEqual("support_escalation", case["route"]["mode"])
        report = self.render(case)
        self.assertIn("现实支持优先", report.splitlines()[0])
        self.assertIn("不要自行停药、换药或调整剂量", report)
        self.assertIn("处方医生或药师", report)
        self.assert_no_ten_part_report(report)

    def test_needs_information_asks_one_route_changing_question(self) -> None:
        case = self.scaffold("我是内向的人。", "v41-needs-information")
        self.assertEqual("needs_information", case["route"]["mode"])
        self.assertEqual("proposed", case["analysis"]["minimal_question"]["status"])
        self.assertTrue(case["analysis"]["minimal_question"]["text"])
        report = self.render(case)
        self.assertIn("需要补充信息", report.splitlines()[0])
        self.assertIn("只补充一个路由问题", report)
        self.assertIn(case["analysis"]["minimal_question"]["text"], report)
        self.assert_no_ten_part_report(report)
        self.assertNotIn("现实实验", report)


if __name__ == "__main__":
    unittest.main()
