from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round98SubjectBindingRedTests(unittest.TestCase):
    """RED regressions for connector splits that orphan the claim subject."""

    def test_subject_and_story_predicate_remain_one_exact_anchor(self) -> None:
        examples = (
            ("老板肯定在架空我。", "interpretation"),
            ("他根本不爱我。", "motive_inference"),
            ("我注定做不成事。", "prediction"),
            ("他就是回避型。", "identity_claim"),
        )
        for text, kind in examples:
            with self.subTest(text=text):
                spans = casefile.generate_source_spans("I1", text)
                self.assertEqual([text], [item["text"] for item in spans])
                self.assertEqual((0, len(text)), (spans[0]["start"], spans[0]["end"]))
                self.assertEqual(
                    kind,
                    casefile.derive_claim_kind_for_span(text, spans[0], text),
                )

    def test_frozen_workplace_story_keeps_its_target(self) -> None:
        text = "老板连续两次没让我参加会议，他肯定在架空我。"
        spans = casefile.generate_source_spans("I1", text)

        self.assertEqual(
            ["老板连续两次没让我参加会议，", "他肯定在架空我。"],
            [item["text"] for item in spans],
        )
        self.assertEqual(
            "interpretation",
            casefile.derive_claim_kind_for_span(spans[1]["text"], spans[1], text),
        )

    def test_complete_epistemic_prefixes_still_form_real_boundaries(self) -> None:
        examples = (
            ("他没回就是不爱我。", ["他没回", "就是不爱我。"]),
            ("我很难过所以他不爱我。", ["我很难过", "所以他不爱我。"]),
            (
                "我认为他在架空我所以他会离开。",
                ["我认为他在架空我", "所以他会离开。"],
            ),
        )
        for text, expected in examples:
            with self.subTest(text=text):
                self.assertEqual(
                    expected,
                    [item["text"] for item in casefile.generate_source_spans("I1", text)],
                )

    def test_subject_and_sequence_or_contrast_adverb_remain_bound(self) -> None:
        for text in (
            "他后来没回消息。",
            "老板随后取消了会议。",
            "我之后没有完成计划。",
            "他同时删除了文档。",
            "他却不爱我。",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    [text],
                    [item["text"] for item in casefile.generate_source_spans("I1", text)],
                )

        text = "他没回消息后来老板取消了会议。"
        self.assertEqual(
            ["他没回消息", "后来老板取消了会议。"],
            [item["text"] for item in casefile.generate_source_spans("I1", text)],
        )

    def test_every_story_kind_can_license_a_following_real_boundary(self) -> None:
        examples = (
            (
                "他是个坏人所以他永远不会回来。",
                ["他是个坏人", "所以他永远不会回来。"],
            ),
            (
                "他存心害我所以他会离开。",
                ["他存心害我", "所以他会离开。"],
            ),
        )
        for text, expected in examples:
            with self.subTest(text=text):
                self.assertEqual(
                    expected,
                    [item["text"] for item in casefile.generate_source_spans("I1", text)],
                )

    def test_sequence_after_feeling_does_not_create_connector_only_span(self) -> None:
        examples = (
            (
                "我很难过后来他没回消息。",
                ["我很难过", "后来他没回消息。"],
            ),
            (
                "我很害怕随后他取消了会议。",
                ["我很害怕", "随后他取消了会议。"],
            ),
            (
                "我很难过同时他不爱我。",
                ["我很难过", "同时他不爱我。"],
            ),
        )
        for text, expected in examples:
            with self.subTest(text=text):
                self.assertEqual(
                    expected,
                    [item["text"] for item in casefile.generate_source_spans("I1", text)],
                )

    def test_full_danshi_connector_is_never_tokenized_as_dan_plus_copula(self) -> None:
        examples = (
            ("他没回但是他不爱我。", ["他没回", "他不爱我。"]),
            (
                "我很难过但是他不爱我。",
                ["我很难过", "他不爱我。"],
            ),
            (
                "他没回但是后来他道歉。",
                ["他没回", "后来他道歉。"],
            ),
        )
        for text, expected in examples:
            with self.subTest(text=text):
                spans = casefile.generate_source_spans("I1", text)
                self.assertEqual(expected, [item["text"] for item in spans])
                self.assertNotIn("是", {item["text"] for item in spans})


if __name__ == "__main__":
    unittest.main()
