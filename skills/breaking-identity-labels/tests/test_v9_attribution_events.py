#!/usr/bin/env python3
"""V9 red tests: bind the attribution predicate to its source actor."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
CLOCK = "2026-08-06T12:00:00Z"


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


def source_for(case: dict, label: str) -> str | None:
    return next(
        (item["source_type"] for item in case["analysis"]["labels"] if item["text"] == label),
        None,
    )


class AttributionPredicateBindingTests(unittest.TestCase):
    def test_intervening_source_words_do_not_replace_the_actual_speaker(self) -> None:
        positives = (
            (
                "同事看过AI给的报告后，仍说我是“冲突退避者”。",
                "冲突退避者",
                "other_person_attribution",
            ),
            (
                "主管把AI生成的摘要转给我，并在评语里称我为“协作断点”。",
                "协作断点",
                "other_person_attribution",
            ),
            (
                "我看完AI答案后仍自称“慢热航行者”。",
                "慢热航行者",
                "user_self_description",
            ),
            (
                "朋友做了测试，他说我是“关系逃兵”。",
                "关系逃兵",
                "other_person_attribution",
            ),
            (
                "朋友读过模型回复后，但他自己仍说我是“回声员工”。",
                "回声员工",
                "other_person_attribution",
            ),
            (
                "短视频博主引用AI回答后，博主随后评价我是“情绪冻结者”。",
                "情绪冻结者",
                "social_media_label",
            ),
        )
        for text, label, expected in positives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual(expected, source_for(case, label))

        controls = (
            ("主管把评语交给AI，AI称我为“协作断点”。", "协作断点", "ai_inference"),
            ("朋友说，模型判断我是“低恢复型”。", "低恢复型", "ai_inference"),
            ("博主做了测试，他说我是“关系逃兵”。", "关系逃兵", "social_media_label"),
            ("短视频博主说，AI把我归为“情绪冻结者”。", "情绪冻结者", "ai_inference"),
        )
        for text, label, expected in controls:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual(expected, source_for(case, label))

    def test_translation_and_record_quotations_do_not_create_a_current_user_label(self) -> None:
        controls = (
            "请翻译“AI says I am an introvert”，不要分析本人。",
            "医院报告引用我自己的原话“我是低能量者”，这只是病历引文，不是诊断。",
            "培训材料把“AI说我是拖延者”列为错误示例，只校对句子，不分析现实用户。",
            "病历模板中的示例是“患者说自己是低恢复型”，目前没有填写任何人的资料。",
        )
        for text in controls:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual([], case["analysis"]["labels"])
                self.assertFalse(case["route"]["trigger"])
                self.assertNotEqual("deconstruct", case["route"]["mode"])

        personal = scaffold("我看完那段翻译后，仍明确自称“低恢复型”，请拆开这个标签。")
        self.assertEqual("user_self_description", source_for(personal, "低恢复型"))
        self.assertTrue(personal["route"]["trigger"])


if __name__ == "__main__":
    unittest.main()
