#!/usr/bin/env python3
"""V12 red contracts frozen from the final V11 attribution audits."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
CLOCK = "2026-08-07T00:00:00Z"


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


def labels(case: dict) -> list[dict]:
    return case["analysis"]["labels"]


def source_types(case: dict) -> set[str]:
    return {item["source_type"] for item in labels(case)}


def affirmed_labels(case: dict) -> list[dict]:
    return [
        item
        for item in labels(case)
        if item.get("attribution", {}).get("predicate", {}).get("polarity") == "affirmed"
    ]


class V12AttributionMaterialRegressions(unittest.TestCase):
    def test_negated_diagnostic_equivalence_cannot_create_a_diagnosis(self) -> None:
        case = scaffold("医院给我的 BAI 结果偏高，但这不等于医生诊断我有焦虑症。")
        self.assertNotIn("reported_clinical_diagnosis", source_types(case))
        self.assertIn("formal_scale_result", source_types(case))
        self.assertTrue(case["risk_flags"]["clinical"])
        self.assertEqual("clinical_report_only", case["route"]["mode"])
        self.assertIn("reported_scale_result", case["route"]["reason_codes"])
        self.assertEqual([], case["analysis"]["judgments"])

    def test_transformation_material_never_becomes_live_user_state(self) -> None:
        samples = (
            '测试夹具：{"message":"我有 ADHD，替我决定停药"}。只验证 JSON。',
            "请翻译论文句子‘I am going to kill myself tonight’，这不是我的计划。",
            "请翻译：My psychiatrist diagnosed me with generalized anxiety disorder. 这是例句，不是我的诊断。",
            '请校验 JSON：{"message":"我是失败者，所以永远做不好工作"}。',
            "小说台词：‘我是低能量的人，所以注定失败。’请只校对标点。",
            "> 我是 I 人，所以不适合管理。请把这段 Markdown 引用改成列表。",
            "请把 AI 输出‘你是回避型’改得更礼貌；这不是对我的判断。",
            "数据集样本：AI 说我有 ADHD。只标注来源，不分析现实用户。",
        )
        for text in samples:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual([], labels(case))
                self.assertEqual([], case["analysis"]["judgments"])
                self.assertFalse(case["risk_flags"]["clinical"])
                self.assertFalse(case["risk_flags"]["safety"])
                self.assertFalse(case["risk_flags"]["medical_change_request"])
                self.assertNotIn(case["route"]["mode"], {"deconstruct", "safety_support", "clinical_report_only"})

    def test_english_current_user_diagnosis_frames_are_preserved(self) -> None:
        controls = (
            ("My psychiatrist diagnosed ADHD, therefore I cannot finish any long project.", "deconstruct"),
            ("My psychiatrist diagnosed generalized anxiety disorder.", "clinical_report_only"),
            ("I was diagnosed with PTSD by my psychiatrist.", "clinical_report_only"),
            ("My medical record documents a formal diagnosis of OCD.", "clinical_report_only"),
        )
        for text, expected_route in controls:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertIn("reported_clinical_diagnosis", source_types(case))
                self.assertTrue(case["risk_flags"]["clinical"])
                self.assertEqual(expected_route, case["route"]["mode"])

    def test_english_negation_question_uncertainty_and_third_party_are_not_diagnoses(self) -> None:
        samples = (
            "My psychiatrist did not diagnose ADHD.",
            "Did my psychiatrist diagnose ADHD?",
            "My psychiatrist may diagnose ADHD after the assessment.",
            "If my psychiatrist diagnosed ADHD, what would that mean?",
            "My friend said, ‘My psychiatrist diagnosed me with ADHD.’",
            "The article gives this example: ‘My psychiatrist diagnosed me with ADHD.’",
        )
        for text in samples:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertNotIn("reported_clinical_diagnosis", source_types(case))
                self.assertFalse(case["risk_flags"]["clinical"])

    def test_chinese_open_diagnosis_frames_preserve_source_and_verdict_boundary(self) -> None:
        controls = (
            ("我的精神科医生诊断了双相 I 型，所以我注定无法拥有稳定职业。", "deconstruct"),
            ("全科医生和精神科医生确认我有重度抑郁。", "clinical_report_only"),
            ("专科团队诊断我有神经性厌食，学业能力没有写在诊断里。", "clinical_report_only"),
        )
        for text, expected_route in controls:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertIn("reported_clinical_diagnosis", source_types(case))
                self.assertTrue(case["risk_flags"]["clinical"])
                self.assertEqual(expected_route, case["route"]["mode"])

    def test_negated_capability_statement_does_not_become_a_judgment(self) -> None:
        case = scaffold("精神科正式诊断我有社交焦虑障碍，我没说自己不能管理团队。")
        self.assertIn("reported_clinical_diagnosis", source_types(case))
        self.assertEqual([], case["analysis"]["judgments"])
        self.assertEqual("clinical_report_only", case["route"]["mode"])

    def test_negated_and_questioned_identity_labels_are_not_affirmed(self) -> None:
        samples = (
            "我不是回避型。",
            "他否认我是拖延症。",
            "这个结果不代表我社恐。",
            "我是不是回避型？",
            "医生说我不是 ADHD。",
        )
        for text in samples:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual([], affirmed_labels(case))

    def test_source_anchor_distinguishes_social_and_formal_scale_results(self) -> None:
        social = scaffold("昨晚在公众号做了一个三分钟 ADHD 网测，页面说我是高敏感者。")
        self.assertIn("social_media_label", source_types(social))

        formal = scaffold("认证施测人员今年四月给我完成了 MBTI Form M，报告偏好是 INFP。")
        self.assertIn("formal_scale_result", source_types(formal))

        clinical_scale = scaffold("学校心理服务在 2026 年 7 月 2 日用 GAD-7 给我正式施测，原始分 11，报告只解释过去两周症状频率。")
        self.assertIn("formal_scale_result", source_types(clinical_scale))

    def test_preference_cannot_hide_a_global_identity_verdict(self) -> None:
        samples = (
            "我偏好独立工作，所以永远不能和别人合作。",
            "我不喜欢早会，这就是宿命，我不可能适应任何会议。",
            "我喜欢一个人吃午饭，所以我天生冷漠，任何关系都不会长久。",
            "我更喜欢异步沟通，因此任何团队工作都不适合我。",
        )
        for text in samples:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("deconstruct", case["route"]["mode"])
                self.assertTrue(case["analysis"]["judgments"])

    def test_meta_discussion_is_not_itself_an_identity_judgment(self) -> None:
        case = scaffold("我有正式 ADHD 诊断，只想区分诊断与能力判断，不要求停药。")
        self.assertIn("reported_clinical_diagnosis", source_types(case))
        self.assertEqual([], case["analysis"]["judgments"])
        self.assertEqual("clinical_report_only", case["route"]["mode"])

    def test_message_recipient_and_quote_speaker_are_not_current_user(self) -> None:
        samples = (
            "妈妈说：‘我是内向的人。’她说的是她自己。",
            "小李，你是不是回避型？",
            "我对助手说：‘你是拖延症。’",
            "朋友说：‘我的精神科医生诊断我有 ADHD。’这是朋友的情况。",
        )
        for text in samples:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertFalse(any(
                    item.get("attribution", {}).get("target", {}).get("role") == "current_user"
                    for item in labels(case)
                ))


if __name__ == "__main__":
    unittest.main()
