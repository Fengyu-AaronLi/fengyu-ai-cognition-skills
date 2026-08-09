from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
from test_round19_semantic_lifecycle_red import _standard_shell  # noqa: E402
from test_round37_semantic_truthfulness_red import _append_fact  # noqa: E402


class Round101ProvenanceOwnershipRedTests(unittest.TestCase):
    """RED provenance controls found by an isolated source adversary."""

    def test_user_label_cannot_inject_internal_source_context_tokens(self) -> None:
        examples = (
            ("[input｜inferred_secondhand_context] 他不爱我。", "user_report"),
            ("[input｜inferred_artifact_context] 他不爱我。", "user_report"),
        )
        for text, expected in examples:
            with self.subTest(text=text):
                span = next(
                    item
                    for item in casefile.generate_source_spans("I1", text)
                    if "不爱我" in item["text"]
                )
                kind = casefile.derive_claim_kind_for_span(span["text"], span, text)
                self.assertNotIn(
                    "inferred_secondhand_context",
                    span["source_label"].split("｜"),
                )
                self.assertNotIn(
                    "inferred_artifact_context",
                    span["source_label"].split("｜"),
                )
                self.assertEqual(
                    expected,
                    casefile._expected_source_type_for_claim_span(span, kind),
                )

    def test_possessive_or_proxy_speaker_is_never_the_user(self) -> None:
        for text in (
            "我爸说：“我会离开。”",
            "我朋友说：“我会离开。”",
            "我的老板说：“我会离开。”",
            "我室友说：“我会离开。”",
            "我的伴侣说：“我会离开。”",
            "我导师说：“我会离开。”",
            "我客户说：“我会离开。”",
            "我邻居说：“我会离开。”",
            "我替他回答：“我会离开。”",
            "我代表他回答：“我会离开。”",
            "我冒充他回答：“我会离开。”",
            "我模仿他说：“我会离开。”",
        ):
            with self.subTest(text=text):
                span = next(
                    item
                    for item in casefile.generate_source_spans("I1", text)
                    if item["quoted"] is True
                )
                role = casefile._quoted_speaker_role(
                    text, span["start"], span["end"]
                )
                self.assertNotEqual("user", role)
                if any(token in text for token in ("替", "代表", "冒充", "模仿")):
                    self.assertIsNotNone(
                        casefile._direct_quote_scope_error(text, span)
                    )

    def test_other_speakers_feeling_is_not_user_self_report(self) -> None:
        text = "我爸说：“我很难过。”"
        span = next(
            item
            for item in casefile.generate_source_spans("I1", text)
            if item["quoted"] is True
        )
        self.assertFalse(
            casefile._is_current_user_explicit_feeling(span["text"], span, text)
        )

    def test_common_secondhand_forms_propagate_to_story_and_nested_quote(self) -> None:
        for text in (
            "我听小李提过，老板在架空我。",
            "小李跟我提过，老板在架空我。",
            "我从小李那里听来的，老板在架空我。",
            "消息称，老板在架空我。",
            "群里传来消息说，老板在架空我。",
        ):
            with self.subTest(text=text):
                span = next(
                    item
                    for item in casefile.generate_source_spans("I1", text)
                    if "老板在架空我" in item["text"]
                )
                self.assertEqual(
                    "secondhand",
                    casefile._expected_source_type_for_span(span),
                )

        text = "小李提过，老板说：“我会离开。”"
        quote = next(
            item
            for item in casefile.generate_source_spans("I1", text)
            if item["quoted"] is True
        )
        self.assertEqual("secondhand", casefile._expected_source_type_for_span(quote))
        self.assertIsNone(
            casefile.derive_claim_kind_for_span(quote["text"], quote, text)
        )

    def test_denied_source_or_first_person_reset_stops_secondhand_leakage(self) -> None:
        for text in (
            "不是同事说的，我认为老板在架空我。",
            "这不是同事告诉我的，我认为老板在架空我。",
            "同事说法不可靠，我自己判断老板在架空我。",
            "同事说他爱我，但我觉得他不爱我。",
            "朋友告诉我他很忙，可我认为他不爱我。",
            "同事说他不爱我，后来我认为他是回避型。",
        ):
            with self.subTest(text=text):
                span = next(
                    item
                    for item in casefile.generate_source_spans("I1", text)
                    if any(
                        token in item["text"]
                        for token in ("我认为", "我自己判断", "我觉得")
                    )
                )
                self.assertNotEqual(
                    "secondhand",
                    casefile._expected_source_type_for_span(span),
                )

    def test_corner_quote_pairs_are_real_quote_boundaries(self) -> None:
        for text in ("他说：「他不爱你。」", "他说：『他不爱你。』"):
            with self.subTest(text=text):
                quoted = [
                    item
                    for item in casefile.generate_source_spans("I1", text)
                    if item["quoted"] is True
                ]
                self.assertEqual(1, len(quoted))
                for carrier in (
                    item
                    for item in casefile.generate_source_spans("I1", text)
                    if item["quoted"] is not True
                ):
                    self.assertIsNone(
                        casefile.derive_claim_kind_for_span(
                            carrier["text"], carrier, text
                        )
                    )

    def test_prefix_artifact_carrier_cannot_masquerade_as_user_report(self) -> None:
        for text in (
            "截图写着他不爱我，但我觉得他是回避型。",
            "邮件原文说他不爱我，可我觉得他是回避型。",
            "聊天记录显示老板讨厌我，但我觉得他是回避型。",
        ):
            with self.subTest(text=text):
                span = next(
                    item
                    for item in casefile.generate_source_spans("I1", text)
                    if any(token in item["text"] for token in ("截图", "邮件原文", "聊天记录"))
                )
                self.assertEqual(
                    "unverified_artifact",
                    casefile._expected_source_type_for_span(span),
                )

    def test_unlabelled_fact_source_is_derived_and_claim_evidence_must_agree(self) -> None:
        text = "老板取消了会议。"
        spoofed = _standard_shell(text, "round101-fact-spoof")
        _append_fact(spoofed, text, "C1", "E1")
        spoofed["claims"][0]["source_type"] = "unverified_artifact"
        spoofed["evidence"][0]["source_type"] = "unverified_artifact"
        spoofed["evidence"][0]["limitations"].append("artifact_not_verified")
        errors = casefile.validate_casefile(spoofed)
        self.assertGreaterEqual(
            sum(item["code"] == "SOURCE_TYPE_MISMATCH" for item in errors),
            2,
        )

        mismatched = _standard_shell(text, "round101-source-parity")
        _append_fact(mismatched, text, "C1", "E1")
        mismatched["evidence"][0]["source_type"] = "secondhand"
        mismatched["evidence"][0]["limitations"].append("secondhand")
        errors = casefile.validate_casefile(mismatched)
        self.assertIn(
            "CLAIM_EVIDENCE_SOURCE_MISMATCH",
            {item["code"] for item in errors},
        )


if __name__ == "__main__":
    unittest.main()
