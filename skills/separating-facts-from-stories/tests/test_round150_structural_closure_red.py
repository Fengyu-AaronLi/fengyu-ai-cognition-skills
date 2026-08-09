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
    draft = casefile.make_draft(text, "round150-structure", "standard")
    quotes = [item for item in draft["source_spans"] if item.get("quoted") is True]
    if not quotes:
        return None
    span = max(quotes, key=lambda item: len(item["text"]))
    return casefile.derive_claim_kind_for_span(span["text"], span, text)


class Round150StructuralClosureRedTests(unittest.TestCase):
    def test_open_document_container_family_is_not_direct_speech(self) -> None:
        for text in (
            "年度报告中老板说：‘手机送修，刚拿回来’。",
            "幻灯片中老板说：‘手机送修，刚拿回来’。",
            "PPT里老板说：‘手机送修，刚拿回来’。",
            "会议简报里老板说：‘手机送修，刚拿回来’。",
        ):
            with self.subTest(text=text):
                self.assertNotEqual("attributed_statement", _kind(text), text)
                self.assertTrue(_forced_attribution_errors(text), text)

    def test_composite_summary_label_and_unfinished_time_family_fail_closed(self) -> None:
        for text in (
            "[内容摘要] 老板说：‘手机送修，刚拿回来’。",
            "三天后老板会说：‘手机送修，刚拿回来’。",
            "到时候老板会说：‘手机送修，刚拿回来’。",
            "待他到场，老板会说：‘手机送修，刚拿回来’。",
        ):
            with self.subTest(text=text):
                self.assertNotEqual("attributed_statement", _kind(text), text)
                self.assertTrue(_forced_attribution_errors(text), text)

    def test_second_task_grammar_handles_connectors_and_bare_questions(self) -> None:
        for text in (
            "整理：老板说他会开除我。顺便说说这话真不真。",
            "整理：老板说他会开除我，再说说消息是否可靠。",
            "整理：老板说他会开除我；评判这段话的可信程度。",
            "整理：老板说他会开除我；解读一下他的意图。",
            "整理：老板说他会开除我；这话靠谱吗？",
        ):
            with self.subTest(text=text):
                self.assertIsNone(casefile.parse_pure_transform_task(text), text)

    def test_formatting_response_rejects_inferred_truth_and_intent(self) -> None:
        request = "整理：老板说他会开除我。"
        for response in (
            "老板说他会开除我。这说明他想开除你。",
            "老板说他会开除我。这话八成是真的。",
            "老板说他会开除我。消息来源看起来可靠。",
        ):
            with self.subTest(response=response):
                valid, errors = workflow.validate_passthrough_response(
                    "formatting", request, response
                )
                self.assertFalse(valid, response)
                self.assertIn("epistemic_content_added", errors)

    def test_direct_and_pure_format_controls_survive(self) -> None:
        self.assertEqual(
            "attributed_statement",
            _kind("老板当面告诉我：‘手机送修，刚拿回来’。"),
        )
        request = "整理：老板问：‘这话靠谱吗？’"
        self.assertEqual("formatting", casefile.parse_pure_transform_task(request)["kind"])
        self.assertEqual(
            (True, []),
            workflow.validate_passthrough_response(
                "formatting", request, "老板问：‘这话靠谱吗？’"
            ),
        )


if __name__ == "__main__":
    unittest.main()
