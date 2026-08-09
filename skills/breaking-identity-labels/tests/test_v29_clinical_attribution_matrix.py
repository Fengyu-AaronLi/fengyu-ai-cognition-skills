#!/usr/bin/env python3
"""V29 red contracts for diagnosis ownership and formal-scale provenance."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "identity_label_case.py"
SPEC = importlib.util.spec_from_file_location("identity_label_runtime_v29", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load identity label runtime")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
CLOCK = "2026-08-06T00:00:00Z"


def scaffold(text: str) -> dict:
    return MODULE.scaffold_case(text, None, CLOCK)


class ClinicalAttributionMatrixTests(unittest.TestCase):
    def test_third_party_diagnosis_never_becomes_the_current_user(self) -> None:
        cases = (
            "医生告诉我，我女儿患有 ADHD；这不是我的诊断。",
            "医生告诉我，我丈夫患有双相情感障碍；这是他的诊断，不是我的。",
        )
        for text in cases:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual([], case["analysis"]["labels"])
                clinical_claims = [
                    item for item in case["analysis"]["context_claims"]
                    if item["source"] == "reported_clinical_diagnosis"
                ]
                self.assertTrue(clinical_claims, case["analysis"])
                self.assertTrue(
                    all(item["subject"] == "third_party" for item in clinical_claims),
                    clinical_claims,
                )

    def test_common_current_user_diagnosis_forms_are_preserved(self) -> None:
        cases = (
            "经主治医生完整评估，我最终拿到的诊断是成人 ADHD。",
            "评估结束后，医生给我的诊断是自闭症谱系障碍。",
            "我拿到医生签字的诊断书，写的是 PTSD。",
            "我的精神科病历记录诊断：广泛性焦虑障碍。",
            "医生正式评估后给我下了成人 ADHD 诊断。",
        )
        for text in cases:
            with self.subTest(text=text):
                case = scaffold(text)
                clinical_labels = [
                    item for item in case["analysis"]["labels"]
                    if item["source_type"] == "reported_clinical_diagnosis"
                ]
                self.assertTrue(clinical_labels, case["analysis"])
                self.assertTrue(case["risk_flags"]["clinical"])
                self.assertEqual("clinical_report_only", case["route"]["mode"])
                self.assertTrue(
                    all(
                        item["attribution"]["target"]["role"] == "current_user"
                        for item in clinical_labels
                    )
                )

    def test_self_administered_or_ai_scales_are_not_formal_results(self) -> None:
        cases = (
            "我从网上下载 ASRS-v1.1 自己填，得分18，不是正式施测。",
            "我在公众号完成 PHQ-9，得分24，这不是正式施测。",
            "我下载量表自己填写 PHQ-9 得分24，没有专业人员施测。",
            "AI给我做PHQ-9，得分24，它说我有重度抑郁症。",
        )
        for text in cases:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertNotIn(
                    "formal_scale_result",
                    {item["source_type"] for item in case["analysis"]["labels"]},
                    case["analysis"],
                )
                self.assertNotEqual("clinical_report_only", case["route"]["mode"])
                self.assertFalse(case["risk_flags"]["clinical"])

    def test_professionally_administered_scale_remains_formal(self) -> None:
        case = scaffold("医院心理科本周正式施测 PHQ-9，报告记录总分 24。")
        self.assertIn(
            "formal_scale_result",
            {item["source_type"] for item in case["analysis"]["labels"]},
        )
        self.assertEqual("clinical_report_only", case["route"]["mode"])


if __name__ == "__main__":
    unittest.main()
