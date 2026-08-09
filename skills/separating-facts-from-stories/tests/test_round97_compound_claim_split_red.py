from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
from test_round19_semantic_lifecycle_red import _append_story, _standard_shell  # noqa: E402


class Round97CompoundClaimSplitRedTests(unittest.TestCase):
    """RED regressions for two epistemic layers joined by a comma."""

    def test_relationship_prompt_separates_love_story_from_identity_label(self) -> None:
        text = "他是不是不爱我了，是不是回避型。"
        spans = casefile.generate_source_spans("I1", text)

        self.assertEqual(
            ["他是不是不爱我了，", "是不是回避型。"],
            [item["text"] for item in spans],
        )
        self.assertEqual([(0, 9), (9, 16)], [(item["start"], item["end"]) for item in spans])
        self.assertEqual(
            ["motive_inference", "identity_claim"],
            [
                casefile.derive_claim_kind_for_span(item["text"], item, text)
                for item in spans
            ],
        )

    def test_full_frozen_relationship_input_exposes_both_story_layers(self) -> None:
        text = (
            "他看了消息六个小时没回。别跟我说不确定，你直接告诉我，"
            "他是不是不爱我了，是不是回避型。"
        )
        spans = casefile.generate_source_spans("I1", text)
        self.assertEqual([f"SP{index}" for index in range(1, 6)], [item["id"] for item in spans])
        self.assertEqual(
            [(0, 12), (12, 20), (20, 27), (27, 36), (36, 43)],
            [(item["start"], item["end"]) for item in spans],
        )
        for item in spans:
            self.assertEqual(text[item["start"] : item["end"]], item["text"])
            self.assertEqual(casefile.sha256_text(item["text"]), item["sha256"])
        story_spans = [
            item
            for item in spans
            if casefile.derive_claim_kind_for_span(item["text"], item, text)
            in {"motive_inference", "identity_claim"}
        ]

        self.assertEqual(
            ["他是不是不爱我了，", "是不是回避型。"],
            [item["text"] for item in story_spans],
        )
        self.assertEqual(["input", "input"], [item["source_label"] for item in story_spans])
        self.assertEqual(
            [None, None],
            [casefile._expected_source_type_for_span(item) for item in story_spans],
        )
        missing_story_messages = [
            item["message"]
            for item in casefile.validate_casefile(
                casefile.make_draft(text, "round97-frozen-coverage", "standard")
            )
            if item["code"] == "USER_STORY_CLAIM_MISSING"
        ]
        self.assertEqual(
            [
                "recognized current motive_inference was omitted: SP4",
                "recognized current identity_claim was omitted: SP5",
            ],
            missing_story_messages,
        )

    def test_true_epistemic_qualification_remains_bound_to_event(self) -> None:
        for text in (
            "他看了消息，这是真的吗？",
            "老板取消了会议，是否发生？",
            "老板取消了会议，是不是确有发生？",
            "老板取消了会议，是否真的发生？",
            "老板取消了会议，是否取消了？",
        ):
            with self.subTest(text=text):
                spans = casefile.generate_source_spans("I1", text)

                self.assertEqual([text], [item["text"] for item in spans])
                self.assertIsNone(casefile.derive_observation_type(text, spans[0]))

    def test_real_secondhand_context_still_propagates_to_both_story_layers(self) -> None:
        text = "同事告诉我，他是不是不爱我了，是不是回避型。"
        spans = casefile.generate_source_spans("I1", text)
        story_spans = [
            item
            for item in spans
            if casefile.derive_claim_kind_for_span(item["text"], item, text)
            in {"motive_inference", "identity_claim"}
        ]

        self.assertEqual(2, len(story_spans))
        self.assertEqual(
            ["secondhand", "secondhand"],
            [casefile._expected_source_type_for_span(item) for item in story_spans],
        )

    def test_answer_requests_do_not_masquerade_as_secondhand_provenance(self) -> None:
        for prefix in ("请直接告诉我，", "直接告诉我，", "麻烦你告诉我，"):
            text = f"{prefix}他是不是不爱我了，是不是回避型。"
            with self.subTest(prefix=prefix):
                story_spans = [
                    item
                    for item in casefile.generate_source_spans("I1", text)
                    if casefile.derive_claim_kind_for_span(item["text"], item, text)
                    in {"motive_inference", "identity_claim"}
                ]
                self.assertEqual(2, len(story_spans))
                self.assertEqual(
                    [None, None],
                    [casefile._expected_source_type_for_span(item) for item in story_spans],
                )

    def test_unlabelled_story_cannot_self_declare_secondhand_source_type(self) -> None:
        frozen = (
            "他看了消息六个小时没回。别跟我说不确定，你直接告诉我，"
            "他是不是不爱我了，是不是回避型。"
        )
        spoofed = _standard_shell(frozen, "round97-source-spoof")
        _append_story(spoofed, "他是不是不爱我了，", "motive_inference")
        spoofed["claims"][0]["source_type"] = "secondhand"
        spoofed["evidence"][0]["source_type"] = "secondhand"
        errors = casefile.validate_casefile(spoofed)
        self.assertGreaterEqual(
            sum(item["code"] == "SOURCE_TYPE_MISMATCH" for item in errors),
            2,
        )

        real_report = "同事告诉我，他是不是不爱我了，是不是回避型。"
        genuine = _standard_shell(real_report, "round97-real-secondhand")
        _append_story(genuine, "他是不是不爱我了，", "motive_inference")
        genuine["claims"][0]["source_type"] = "secondhand"
        genuine["evidence"][0]["source_type"] = "secondhand"
        self.assertNotIn(
            "SOURCE_TYPE_MISMATCH",
            {item["code"] for item in casefile.validate_casefile(genuine)},
        )

    def test_a_not_a_motive_question_is_not_fragmented_at_second_copula(self) -> None:
        text = "他没回，是不是故意躲我？"
        spans = casefile.generate_source_spans("I1", text)

        self.assertEqual(
            ["他没回，", "是不是故意躲我？"],
            [item["text"] for item in spans],
        )
        self.assertEqual(
            "motive_inference",
            casefile.derive_claim_kind_for_span(spans[1]["text"], spans[1], text),
        )

    def test_negated_motive_phrase_is_not_fragmented_at_copula(self) -> None:
        text = "他不是故意躲我。"
        spans = casefile.generate_source_spans("I1", text)

        self.assertEqual([text], [item["text"] for item in spans])
        self.assertEqual(
            "motive_inference",
            casefile.derive_claim_kind_for_span(text, spans[0], text),
        )

    def test_polar_question_frame_is_not_cut_off_before_story_modifier(self) -> None:
        examples = (
            ("他是不是根本不爱我。", "motive_inference"),
            ("他是不是肯定不爱我。", "motive_inference"),
            ("他会不会根本不爱我。", "motive_inference"),
            ("我是不是注定做不成事。", "prediction"),
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

    def test_ascii_comma_has_the_same_compound_story_boundary(self) -> None:
        text = "他是不是不爱我了,是不是回避型。"
        spans = casefile.generate_source_spans("I1", text)

        self.assertEqual(
            ["他是不是不爱我了,", "是不是回避型。"],
            [item["text"] for item in spans],
        )
        self.assertEqual(
            ["motive_inference", "identity_claim"],
            [casefile.derive_claim_kind_for_span(item["text"], item, text) for item in spans],
        )

    def test_story_tail_detection_uses_all_claim_kinds_not_one_marker_list(self) -> None:
        examples = (
            ("他是不是不爱我了，是不是个坏人。", "identity_claim"),
            ("他是不是不爱我了，是不是自私的人。", "identity_claim"),
            ("他是不是不爱我了，是不是存心躲我。", "motive_inference"),
            ("他是不是不爱我了，是不是未来会离开。", "prediction"),
        )
        for text, second_kind in examples:
            with self.subTest(text=text):
                spans = casefile.generate_source_spans("I1", text)
                self.assertEqual(2, len(spans))
                self.assertEqual(
                    ["motive_inference", second_kind],
                    [
                        casefile.derive_claim_kind_for_span(item["text"], item, text)
                        for item in spans
                    ],
                )

        event_and_identity = "老板取消了会议，是不是个坏人？"
        spans = casefile.generate_source_spans("I1", event_and_identity)
        self.assertEqual(["老板取消了会议，", "是不是个坏人？"], [item["text"] for item in spans])
        self.assertEqual(
            "participation_or_schedule_event",
            casefile.derive_observation_type(spans[0]["text"], spans[0]),
        )
        self.assertEqual(
            "identity_claim",
            casefile.derive_claim_kind_for_span(spans[1]["text"], spans[1], event_and_identity),
        )

    def test_quoted_compound_question_does_not_become_the_users_story(self) -> None:
        text = "他说：“他是不是不爱我了，是不是回避型。”"
        quoted = [
            item
            for item in casefile.generate_source_spans("I1", text)
            if item["quoted"] is True
        ]

        self.assertEqual(
            ["他是不是不爱我了，", "他是不是不爱我了，是不是回避型。", "是不是回避型。"],
            [item["text"] for item in quoted],
        )
        self.assertEqual(
            [None, None, None],
            [casefile.derive_claim_kind_for_span(item["text"], item, text) for item in quoted],
        )

    def test_disavowed_compound_story_does_not_reappear_as_current_claims(self) -> None:
        text = "我没有认为他不爱我，也没判断他是回避型。"
        spans = casefile.generate_source_spans("I1", text)

        self.assertEqual(
            [None, None],
            [casefile.derive_claim_kind_for_span(item["text"], item, text) for item in spans],
        )


if __name__ == "__main__":
    unittest.main()
