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


class Round105ProvenanceClosureRedTests(unittest.TestCase):
    """RED closure tests for compositional provenance structures."""

    def test_compound_secondhand_labels_conservatively_bound_all_carriers(
        self,
    ) -> None:
        tagged_quotes = (
            "[二手｜邮件] 他说：\u201c我会离开。\u201d",
            "[邮件｜二手] 他说：\u201c我会离开。\u201d",
            "[转述｜聊天记录] 他说：\u201c我会离开。\u201d",
            "[语音｜间接来源] 他说：\u201c我会离开。\u201d",
            "[据说｜邮件] 他说：\u201c我会离开。\u201d",
        )
        for text in tagged_quotes:
            with self.subTest(text=text):
                span = next(
                    item
                    for item in casefile.generate_source_spans("I1", text)
                    if item["quoted"] is True
                )
                self.assertEqual(
                    "secondhand",
                    casefile._expected_source_type_for_span(span),
                )
                self.assertIsNone(
                    casefile.derive_claim_kind_for_span(
                        span["text"], span, text
                    )
                )

                spoofed = _standard_shell(text, "round105-compound-quote")
                _append_stated_position(
                    spoofed, span["text"], "C1", "E1"
                )
                self.assertTrue(
                    _codes(spoofed)
                    & {
                        "SOURCE_TYPE_MISMATCH",
                        "DIRECT_QUOTE_NOT_ASSERTED",
                        "CLAIM_KIND_NOT_DERIVED",
                    }
                )

        tagged_stories = (
            "[二手｜截图] 他不爱我。",
            "[截图｜二手] 他不爱我。",
            "[转述｜附件] 老板在架空我。",
            "[文档｜间接来源] 老板在架空我。",
        )
        for text in tagged_stories:
            with self.subTest(text=text):
                spoofed = _standard_shell(text, "round105-compound-story")
                span, kind = _story_span(spoofed, text)
                self.assertEqual(
                    "secondhand",
                    casefile._expected_source_type_for_claim_span(
                        span, kind
                    ),
                )

                _append_story(spoofed, span["text"], kind)
                spoofed["claims"][0]["source_type"] = (
                    "unverified_artifact"
                )
                spoofed["evidence"][0]["source_type"] = (
                    "unverified_artifact"
                )
                spoofed["evidence"][0]["limitations"].append(
                    "artifact_not_verified"
                )
                self.assertIn("SOURCE_TYPE_MISMATCH", _codes(spoofed))

    def test_proxy_and_message_sending_structures_never_become_direct_speech(
        self,
    ) -> None:
        prefixes = (
            "我用他的账号回复",
            "我登录他的账号回复",
            "我借他的身份回复",
            "我顶着他的名义回答",
            "我按他的意思回答",
            "我照他的指示回答",
            "我遵照他的要求回答",
            "我根据他的要求回答",
            "我受托于他回答",
            "我按他的口径回答",
            "我照着他给的话术回答",
            "我复制他的答案回复",
            "我把他的答案当作回复",
            "我冒用他的账号回答",
            "我以他的账号回复",
            "我用老板的账号回复",
            "我按老板要求回复",
            "我照老板指示回答",
        )
        for prefix in prefixes:
            text = f"{prefix}：\u201c我会离开。\u201d"
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

                spoofed = _standard_shell(text, "round105-proxy")
                _append_stated_position(
                    spoofed, span["text"], "C1", "E1"
                )
                self.assertTrue(
                    _codes(spoofed)
                    & {"DIRECT_QUOTE_NOT_ASSERTED", "CLAIM_KIND_NOT_DERIVED"}
                )

    def test_fresh_hearsay_grammar_cannot_fall_back_to_user_report(self) -> None:
        prefixes = (
            "据可靠消息，",
            "据内部消息，",
            "一个熟人说，",
            "熟人跟我提了一嘴，",
            "听人念叨，",
            "听朋友念叨过，",
            "群里都在传，",
            "群里流传，",
            "外界盛传，",
            "有风声说，",
            "听到风声说，",
            "知情人放话，",
            "同事放话，",
            "内部渠道传出，",
            "我从内部渠道了解到，",
            "我经由朋友得知，",
            "我被告知，",
            "人家都说，",
            "大家都在说，",
            "圈内都在传，",
        )
        for prefix in prefixes:
            text = f"{prefix}老板在架空我。"
            with self.subTest(text=text):
                spoofed = _standard_shell(text, "round105-fresh-hearsay")
                span, kind = _story_span(spoofed, text)
                self.assertEqual(
                    "secondhand",
                    casefile._expected_source_type_for_claim_span(
                        span, kind
                    ),
                )

                _append_story(spoofed, span["text"], kind)
                self.assertIn("SOURCE_TYPE_MISMATCH", _codes(spoofed))


if __name__ == "__main__":
    unittest.main()
