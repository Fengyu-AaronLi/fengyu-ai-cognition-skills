from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
from test_round136_assertion_provenance_metamorphic_red import (  # noqa: E402
    _forced_attribution_errors,
)


ARTIFACT_OR_NONREAL_CARRIERS = (
    "[截屏] 老板说：‘手机送修，刚拿回来’。",
    "培训材料里老板说：‘手机送修，刚拿回来’。",
    "PDF里老板说：‘手机送修，刚拿回来’。",
    "网页里老板说：‘手机送修，刚拿回来’。",
    "童话里老板说：‘手机送修，刚拿回来’。",
    "漫画里老板说：‘手机送修，刚拿回来’。",
    "天气预报说：‘明天有雨’。",
    "研究论文说：‘收入增长’。",
)

NONASSERTED_TIME_OR_CONDITION = (
    "倘若他到场，他会说：‘手机送修，刚拿回来’。",
    "假若他到场，他会说：‘手机送修，刚拿回来’。",
    "若他到场，他会说：‘手机送修，刚拿回来’。",
    "即使他到场，他也会说：‘手机送修，刚拿回来’。",
    "一旦他到场，他就会说：‘手机送修，刚拿回来’。",
    "他下周会说：‘手机送修，刚拿回来’。",
    "他下个月会说：‘手机送修，刚拿回来’。",
    "他将来可能会说：‘手机送修，刚拿回来’。",
)

MARKDOWN_SECONDHAND = (
    "同事告诉我：\n- 老板说：‘手机送修，刚拿回来’。",
    "同事告诉我：\n* 老板说：‘手机送修，刚拿回来’。",
    "同事告诉我：\n1. 老板说：‘手机送修，刚拿回来’。",
    "同事告诉我：\n> 老板说：‘手机送修，刚拿回来’。",
)

NONVERBATIM_OR_UNCONFIRMED = (
    "[非原话] 老板说：‘手机送修，刚拿回来’。",
    "[意译] 老板说：‘手机送修，刚拿回来’。",
    "[待确认] 老板说：‘手机送修，刚拿回来’。",
    "[未核实] 老板说：‘手机送修，刚拿回来’。",
    "我用自己的话概括，老板说：‘手机送修，刚拿回来’。",
)


def _derive(text: str) -> str | None:
    draft = casefile.make_draft(text, "round141-provenance", "standard")
    quoted = [
        item for item in draft["source_spans"] if item.get("quoted") is True
    ]
    if not quoted:
        return None
    span = max(quoted, key=lambda item: len(item["text"]))
    return casefile.derive_claim_kind_for_span(span["text"], span, text)


class Round141ProvenanceAndRouteBlindRedTests(unittest.TestCase):
    def assert_not_directly_attributed(self, text: str) -> None:
        self.assertNotEqual("attributed_statement", _derive(text), text)
        self.assertTrue(_forced_attribution_errors(text), text)

    def test_artifact_and_nonreal_carrier_synonyms_are_not_direct(self) -> None:
        for text in ARTIFACT_OR_NONREAL_CARRIERS:
            with self.subTest(text=text):
                self.assert_not_directly_attributed(text)

    def test_future_and_conditional_utterances_are_not_current_speech(self) -> None:
        for text in NONASSERTED_TIME_OR_CONDITION:
            with self.subTest(text=text):
                self.assert_not_directly_attributed(text)

    def test_markdown_does_not_break_secondhand_scope(self) -> None:
        for text in MARKDOWN_SECONDHAND:
            with self.subTest(text=text):
                self.assert_not_directly_attributed(text)

    def test_direct_reset_requires_the_user_to_be_the_recipient(self) -> None:
        for recipient in ("秘书", "助理", "同事", "朋友"):
            text = (
                f"据同事转述，但老板当面告诉{recipient}："
                "‘手机送修，刚拿回来’。"
            )
            with self.subTest(recipient=recipient):
                self.assert_not_directly_attributed(text)
        self.assertEqual(
            "attributed_statement",
            _derive("据说项目要停，但老板当面告诉我：‘手机送修，刚拿回来’。"),
        )

    def test_nonverbatim_or_unconfirmed_labels_are_not_direct(self) -> None:
        for text in NONVERBATIM_OR_UNCONFIRMED:
            with self.subTest(text=text):
                self.assert_not_directly_attributed(text)

    def test_formatting_with_truth_or_source_request_is_not_passthrough(self) -> None:
        for text in (
            "整理：老板说他会开除我；请核实来源。",
            "整理：老板说他会开除我；请判断真假。",
            "整理：老板说他会开除我；请解释含义。",
            "整理成项目符号：老板说他会开除我；再分析他的动机。",
        ):
            with self.subTest(text=text):
                self.assertIsNone(casefile.parse_pure_transform_task(text))
                self.assertEqual(
                    "standard",
                    casefile.make_draft(text, "round141-route", "auto")["mode"],
                )

    def test_true_format_only_control_remains_passthrough(self) -> None:
        text = "把这句话改成项目符号：她只回复了一个‘嗯’。"
        self.assertIsNotNone(casefile.parse_pure_transform_task(text))
        self.assertEqual(
            "passthrough",
            casefile.make_draft(text, "round141-format-control", "auto")["mode"],
        )


if __name__ == "__main__":
    unittest.main()
