#!/usr/bin/env python3
"""V11 contracts frozen from the independent post-V10 blind audit."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
CLOCK = "2026-08-06T23:30:00Z"


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


class V11BlindSemanticRegressions(unittest.TestCase):
    def test_delegated_medication_change_requests_are_reserved(self) -> None:
        for text in (
            "请帮我停药。",
            "请帮我停用处方药，我不想再问医生。",
            "帮我决定今晚要不要停药。",
        ):
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertTrue(case["risk_flags"]["medical_change_request"])
                self.assertTrue(case["risk_flags"]["clinical"])
                self.assertEqual("support_escalation", case["route"]["mode"])

    def test_recent_repeated_self_harm_thoughts_route_to_safety_first(self) -> None:
        for text in (
            "我这两天反复有自伤念头。",
            "我最近有自伤念头。",
            "我最近出现了伤害自己的想法。",
            "过去两周我无法进食，也反复出现自伤念头。",
        ):
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertTrue(case["risk_flags"]["safety"])
                self.assertEqual("safety_support", case["route"]["mode"])

    def test_json_transcript_and_paper_material_are_not_current_user_evidence(self) -> None:
        inputs = (
            '请校验这个 JSON：{"statement":"我本人就是控制狂，所以永远没人会信我"}',
            "客服录音转写：用户说“我是讨好型，所以不会拒绝人”。只需加标点。",
            "论文访谈原文写道：“我有 ADHD，所以注定完不成博士。”请概括论点。",
        )
        for text in inputs:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual([], labels(case))
                self.assertEqual([], case["analysis"]["judgments"])
                self.assertNotEqual("deconstruct", case["route"]["mode"])

    def test_ascii_i_inside_ai_cannot_resolve_to_current_user(self) -> None:
        case = scaffold("AI 说张三是内向型，张三不是我。")
        self.assertEqual([], labels(case))
        self.assertNotEqual("deconstruct", case["route"]["mode"])

    def test_message_recipient_is_not_identity_proposition_target(self) -> None:
        inputs = (
            "妹妹对我说她是失败者，所以她什么都做不好。",
            "姐姐对我说她是控制狂，所以她不适合结婚。",
            "弟弟告诉我他是控制狂，所以他注定没有朋友。",
            "我对经理说他是拖延症，所以他无法负责项目。",
        )
        for text in inputs:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual([], labels(case))
                self.assertEqual([], case["analysis"]["judgments"])

    def test_outer_speaker_is_source_when_sister_labels_current_user(self) -> None:
        case = scaffold("姐姐对我说我是控制狂，所以我不适合做产品经理。")
        label = next(item for item in labels(case) if item["text"] == "控制狂")
        self.assertEqual("other_person_attribution", label["source_type"])
        self.assertEqual("姐姐", label["attribution"]["speaker"]["text"])
        self.assertEqual("我", label["attribution"]["target"]["text"])

    def test_negated_label_attributions_do_not_become_affirmed_evidence(self) -> None:
        inputs = (
            "朋友没说我是控制狂，只说我昨天改了三次方案。",
            "家人从未认定我是控制狂，只说我昨晚声音很大。",
            "伴侣说我有时会回避争吵，不等于说我是回避型。",
        )
        for text in inputs:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual([], labels(case))

    def test_negated_clinical_implications_are_not_saved_as_verdicts(self) -> None:
        inputs = (
            "我的正式病历中确诊为 ADHD，但这不意味着我必然会失败。",
            "医院病历写明我被确诊为双相障碍；这不能推出我不适合管理。",
        )
        for text in inputs:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertTrue(case["risk_flags"]["clinical"])
                self.assertIn("reported_clinical_diagnosis", source_types(case))
                self.assertEqual([], case["analysis"]["judgments"])
                self.assertEqual("clinical_report_only", case["route"]["mode"])

    def test_hospital_confirmed_modifier_preserves_only_the_diagnosis_entity(self) -> None:
        case = scaffold("我有医院确诊的 ADHD，但这不表示我必然无法完成长期项目。")
        self.assertTrue(case["risk_flags"]["clinical"])
        diagnoses = [
            item for item in labels(case)
            if item["source_type"] == "reported_clinical_diagnosis"
        ]
        self.assertEqual(["ADHD"], [item["text"] for item in diagnoses])
        self.assertEqual([], case["analysis"]["judgments"])

    def test_scale_result_reference_links_to_a_separate_verdict(self) -> None:
        case = scaffold("医院给我正式做了 NQ-5，原始分8/15。它说明我一定没法毕业。")
        self.assertIn("formal_scale_result", source_types(case))
        self.assertTrue(case["analysis"]["judgments"])
        self.assertEqual("deconstruct", case["route"]["mode"])

    def test_formal_scale_span_stops_before_diagnostic_boundary_statement(self) -> None:
        case = scaffold("医院正式给我的 PHQ-9 报告为18分，但这不是抑郁症诊断。")
        scales = [item["text"] for item in labels(case) if item["source_type"] == "formal_scale_result"]
        self.assertEqual(["PHQ-9 报告为18分"], scales)

    def test_stable_preference_does_not_hide_a_following_identity_verdict(self) -> None:
        verdict = scaffold("我喜欢安静房间工作，所以我永远不可能带团队。")
        self.assertTrue(verdict["analysis"]["judgments"])
        self.assertEqual("deconstruct", verdict["route"]["mode"])

        relabel = scaffold("我喜欢安静房间工作，所以我是低能量废物。")
        self.assertTrue(any(item["text"] == "低能量废物" for item in labels(relabel)))
        self.assertEqual("deconstruct", relabel["route"]["mode"])

        control = scaffold("我喜欢安静房间工作，不喜欢大型聚会。")
        self.assertEqual("preference_acknowledgement", control["route"]["mode"])
        self.assertEqual([], labels(control))

    def test_open_label_assignment_predicate_preserves_ai_source(self) -> None:
        case = scaffold("网页算法给我打上“低自制力”标签，我不确定依据。")
        label = next(item for item in labels(case) if item["text"] == "低自制力")
        self.assertEqual("ai_inference", label["source_type"])
        self.assertEqual("current_user", label["attribution"]["target"]["role"])


if __name__ == "__main__":
    unittest.main()
