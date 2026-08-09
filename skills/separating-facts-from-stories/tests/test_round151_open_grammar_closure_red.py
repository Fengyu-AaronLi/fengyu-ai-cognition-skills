from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
import workflow  # noqa: E402
from test_round136_assertion_provenance_metamorphic_red import (  # noqa: E402
    _forced_attribution_errors,
)


def _kind(text: str) -> str | None:
    draft = casefile.make_draft(text, "round151-open-grammar", "standard")
    quotes = [item for item in draft["source_spans"] if item.get("quoted") is True]
    if not quotes:
        return None
    span = max(quotes, key=lambda item: len(item["text"]))
    return casefile.derive_claim_kind_for_span(span["text"], span, text)


class Round151OpenGrammarClosureRedTests(unittest.TestCase):
    def test_compound_artifact_carriers_are_not_direct_speech(self) -> None:
        for text in (
            "Excel表里老板说：‘手机送修，刚拿回来’。",
            "工作日志里老板说：‘手机送修，刚拿回来’。",
        ):
            with self.subTest(text=text):
                self.assertNotEqual("attributed_statement", _kind(text), text)
                self.assertTrue(_forced_attribution_errors(text), text)

    def test_open_summary_markers_are_not_direct_speech(self) -> None:
        for text in (
            "[摘录] 老板说：‘手机送修，刚拿回来’。",
            "按我的理解概括，老板说：‘手机送修，刚拿回来’。",
        ):
            with self.subTest(text=text):
                self.assertNotEqual("attributed_statement", _kind(text), text)
                self.assertTrue(_forced_attribution_errors(text), text)

    def test_wait_until_condition_is_not_completed_direct_speech(self) -> None:
        text = "等他到场之后，老板会说：‘手机送修，刚拿回来’。"
        self.assertNotEqual("attributed_statement", _kind(text), text)
        self.assertTrue(_forced_attribution_errors(text), text)

    def test_chinese_and_english_second_tasks_cannot_enter_formatting_bypass(self) -> None:
        for text in (
            "整理：老板说他会开除我；顺带看看这话是否经得起推敲。",
            "Put this sentence in a Markdown blockquote: My boss said he would fire me; "
            "assess whether the claim is credible.",
        ):
            with self.subTest(text=text):
                self.assertIsNone(casefile.parse_pure_transform_task(text), text)
                self.assertIsNone(workflow.classify_passthrough_request(text), text)

    def test_english_epistemic_appendix_is_rejected_but_pure_controls_survive(self) -> None:
        request = (
            "Put this sentence in a Markdown blockquote: "
            "My boss said he would fire me."
        )
        response = (
            "> My boss said he would fire me.\n\n"
            "The claim is credible because he sounded serious."
        )
        valid, errors = workflow.validate_passthrough_response(
            "formatting", request, response
        )
        self.assertFalse(valid)
        self.assertIn("epistemic_content_added", errors)

        self.assertEqual("formatting", casefile.parse_pure_transform_task(request)["kind"])
        self.assertEqual("formatting", workflow.classify_passthrough_request(request))
        self.assertEqual(
            (True, []),
            workflow.validate_passthrough_response(
                "formatting", request, "> My boss said he would fire me."
            ),
        )
        self.assertEqual(
            "attributed_statement",
            _kind("今天老板当面对我说：‘手机送修，刚拿回来’。"),
        )


if __name__ == "__main__":
    unittest.main()
