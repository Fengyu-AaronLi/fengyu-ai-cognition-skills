from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round100AssertionScopeAndCompositionRedTests(unittest.TestCase):
    """RED cases from the third independent adversarial loop."""

    def test_nonasserted_story_scopes_do_not_become_current_user_claims(self) -> None:
        examples = (
            "假设他是回避型。",
            "这不意味着他不爱我。",
            "没证据证明他不爱我。",
            "如果他不爱我，我会离开。",
            "不是因为他不爱我，是因为他在忙。",
        )
        for text in examples:
            with self.subTest(text=text):
                for span in casefile.generate_source_spans("I1", text):
                    if any(
                        token in span["text"]
                        for token in ("回避型", "不爱我")
                    ):
                        self.assertIsNone(
                            casefile.derive_claim_kind_for_span(
                                span["text"], span, text
                            )
                        )

    def test_feeling_boundary_keeps_story_subject_with_modifier(self) -> None:
        text = "我担心他根本不爱我。"
        spans = casefile.generate_source_spans("I1", text)
        self.assertEqual(
            ["我担心", "他根本不爱我。"],
            [item["text"] for item in spans],
        )
        self.assertEqual(
            "motive_inference",
            casefile.derive_claim_kind_for_span(spans[1]["text"], spans[1], text),
        )

    def test_coordinated_story_kinds_are_not_collapsed_by_precedence(self) -> None:
        examples = (
            (
                "他不爱我而且是回避型。",
                ["motive_inference", "identity_claim"],
            ),
            (
                "他不爱我并且是NPD。",
                ["motive_inference", "identity_claim"],
            ),
            (
                "他肯定不爱我而且永远不会回来。",
                ["motive_inference", "prediction"],
            ),
            (
                "老板在架空我并且准备开掉我。",
                ["interpretation", "prediction"],
            ),
        )
        for text, expected_kinds in examples:
            with self.subTest(text=text):
                spans = casefile.generate_source_spans("I1", text)
                kinds = [
                    casefile.derive_claim_kind_for_span(item["text"], item, text)
                    for item in spans
                ]
                self.assertEqual(expected_kinds, kinds)

    def test_explicit_formatting_of_quoted_material_is_passthrough(self) -> None:
        for text in (
            "请整理原文：“他不爱我。”",
            "请把原文“他不爱我”整理一下。",
            "格式化这句：“他不爱我。”",
        ):
            with self.subTest(text=text):
                draft = casefile.make_draft(text, "round100-format", "auto")
                self.assertEqual("passthrough", draft["mode"])
                for span in draft["source_spans"]:
                    if span["quoted"] is not True:
                        self.assertIsNone(
                            casefile.derive_claim_kind_for_span(
                                span["text"], span, text
                            )
                        )

    def test_common_quantity_positions_remain_observable(self) -> None:
        for text in (
            "她取消了两次约会。",
            "她两次取消约会。",
            "她取消两次约会。",
            "她两次都取消约会。",
        ):
            with self.subTest(text=text):
                span = casefile.generate_source_spans("I1", text)[0]
                self.assertEqual(
                    "participation_or_schedule_event",
                    casefile.derive_observation_type(text, span),
                )


if __name__ == "__main__":
    unittest.main()
