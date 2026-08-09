from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
from test_round19_semantic_lifecycle_red import (  # noqa: E402
    _append_stated_position,
    _append_story,
    _standard_shell,
)
from test_round37_semantic_truthfulness_red import _append_fact  # noqa: E402


def _codes(data: dict) -> set[str]:
    return {item["code"] for item in casefile.validate_casefile(data)}


def _story_span(data: dict, input_text: str) -> tuple[dict, str]:
    for span in data["source_spans"]:
        kind = casefile.derive_claim_kind_for_span(
            span["text"], span, input_text
        )
        if kind in {
            "interpretation",
            "motive_inference",
            "identity_claim",
            "prediction",
        }:
            return span, kind
    raise AssertionError(f"no story span found for {input_text!r}")


def _set_story_source(data: dict, source_type: str) -> None:
    data["claims"][0]["source_type"] = source_type
    data["evidence"][0]["source_type"] = source_type
    if source_type == "secondhand":
        data["evidence"][0]["limitations"].append("secondhand")
    elif source_type == "unverified_artifact":
        data["evidence"][0]["limitations"].append(
            "artifact_not_verified"
        )


class Round103ProvenanceCompositionalRedTests(unittest.TestCase):
    """RED matrices for provenance structures missed by finite word lists."""

    def test_proxy_speech_never_becomes_a_direct_current_position(self) -> None:
        prefixes = (
            "我帮他回答",
            "我以他的名义回答",
            "我受他委托回答",
            "我作为他的代表回答",
            "我用他的口吻回答",
            "我以公司名义回复",
        )
        for prefix in prefixes:
            text = f"{prefix}：“我会离开。”"
            with self.subTest(text=text):
                span = next(
                    item
                    for item in casefile.generate_source_spans("I1", text)
                    if item["quoted"] is True
                )
                self.assertIsNotNone(
                    casefile._direct_quote_scope_error(text, span)
                )
                self.assertIsNone(
                    casefile.derive_claim_kind_for_span(
                        span["text"], span, text
                    )
                )

                spoofed = _standard_shell(text, "round103-proxy")
                _append_stated_position(
                    spoofed, span["text"], "C1", "E1"
                )
                self.assertTrue(
                    _codes(spoofed)
                    & {"DIRECT_QUOTE_NOT_ASSERTED", "CLAIM_KIND_NOT_DERIVED"}
                )

    def test_natural_hearsay_forms_cannot_fall_back_to_user_report(self) -> None:
        prefixes = (
            "据传，",
            "传闻称，",
            "听闻，",
            "有人爆料，",
            "同事爆料，",
            "我接到消息，",
        )
        for prefix in prefixes:
            text = f"{prefix}老板在架空我。"
            with self.subTest(text=text):
                spoofed = _standard_shell(text, "round103-hearsay")
                span, kind = _story_span(spoofed, text)
                self.assertEqual(
                    "secondhand",
                    casefile._expected_source_type_for_claim_span(
                        span, kind
                    ),
                )

                _append_story(spoofed, span["text"], kind)
                self.assertIn("SOURCE_TYPE_MISMATCH", _codes(spoofed))

    def test_first_person_ownership_structures_reset_report_context(self) -> None:
        examples = (
            "同事说他很忙，但在我看来他不爱我。",
            "同事说他很忙，但我的判断是他不爱我。",
            "同事说他很忙，不过我个人的判断是他不爱我。",
            "同事说他很忙，可依我看他不爱我。",
            "同事说他很忙，但是就我而言他不爱我。",
            "同事说他很忙，但我个人认为他不爱我。",
        )
        for text in examples:
            with self.subTest(text=text):
                correct = _standard_shell(text, "round103-owner-reset")
                span, kind = _story_span(correct, text)
                self.assertEqual(
                    "user_report",
                    casefile._expected_source_type_for_claim_span(
                        span, kind
                    ),
                )

                _append_story(correct, span["text"], kind)
                self.assertNotIn("SOURCE_TYPE_MISMATCH", _codes(correct))

    def test_artifact_carrier_structures_cannot_become_user_report(self) -> None:
        examples = (
            "截图上写他不爱我。",
            "图片上写着他不爱我。",
            "微信记录里写着他不爱我。",
            "录音里说他不爱我。",
            "邮件中写他不爱我。",
            "短信里写他不爱我。",
            "文档写着他不爱我。",
            "屏幕上显示他不爱我。",
        )
        for text in examples:
            with self.subTest(text=text):
                spoofed = _standard_shell(text, "round103-carrier")
                span, kind = _story_span(spoofed, text)
                self.assertEqual(
                    "unverified_artifact",
                    casefile._expected_source_type_for_claim_span(
                        span, kind
                    ),
                )

                _append_story(spoofed, span["text"], kind)
                self.assertIn("SOURCE_TYPE_MISMATCH", _codes(spoofed))

    def test_explicit_artifact_labels_cannot_upgrade_facts_to_direct_observation(
        self,
    ) -> None:
        labels = (
            "邮件",
            "照片",
            "图片",
            "录音",
            "语音",
            "文档",
            "短信",
            "聊天记录",
            "系统记录",
        )
        for label in labels:
            text = f"[{label}] 老板取消了会议。"
            with self.subTest(text=text):
                spoofed = _standard_shell(text, "round103-artifact-label")
                span = next(
                    item
                    for item in spoofed["source_spans"]
                    if "老板取消了会议" in item["text"]
                )
                self.assertEqual(
                    "unverified_artifact",
                    casefile._expected_source_type_for_claim_span(
                        span, "observable_fact"
                    ),
                )

                _append_fact(spoofed, span["text"], "C1", "E1")
                self.assertIn("SOURCE_TYPE_MISMATCH", _codes(spoofed))

    def test_negated_source_labels_do_not_assert_the_negated_source(self) -> None:
        examples = (
            ("[不是转述] 他不爱我。", "secondhand"),
            ("[并非二手] 他不爱我。", "secondhand"),
            ("[不是截图] 他不爱我。", "unverified_artifact"),
            ("[没有附件] 他不爱我。", "unverified_artifact"),
            ("[并非我的观察] 他不爱我。", "user_direct_observation"),
        )
        for text, spoofed_source_type in examples:
            with self.subTest(text=text):
                spoofed = _standard_shell(text, "round103-label-polarity")
                span, kind = _story_span(spoofed, text)
                self.assertEqual(
                    "user_report",
                    casefile._expected_source_type_for_claim_span(
                        span, kind
                    ),
                )

                _append_story(spoofed, span["text"], kind)
                _set_story_source(spoofed, spoofed_source_type)
                self.assertIn("SOURCE_TYPE_MISMATCH", _codes(spoofed))


if __name__ == "__main__":
    unittest.main()
