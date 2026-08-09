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
    _standard_shell,
)


NON_SPEECH_QUOTE_CONTEXTS = (
    "机器人生成了“我会留下”。",
    "页面标题是“我会留下”。",
    "截图上写着“我会留下”。",
    "我想说“我会留下”。",
    "他曾说“我会留下”。",
)


class Round34QuoteProvenanceRedTests(unittest.TestCase):
    def test_only_current_asserted_speech_with_a_known_speaker_is_a_position(self) -> None:
        for text in NON_SPEECH_QUOTE_CONTEXTS:
            with self.subTest(text=text):
                quote = next(
                    span
                    for span in casefile.generate_source_spans("I1", text)
                    if span["quoted"] and span["text"] == "我会留下"
                )
                self.assertIsNotNone(
                    casefile._direct_quote_scope_error(text, quote),
                    "generated, artifact, intended, or past text is not a current speech act",
                )
                self.assertNotEqual(
                    "stated_position",
                    casefile.derive_claim_kind_for_span(
                        quote["text"], quote, text
                    ),
                )

        for text in ("我现在说“我会留下”。", "他现在说“我会留下”。"):
            with self.subTest(positive=text):
                quote = next(
                    span
                    for span in casefile.generate_source_spans("I1", text)
                    if span["quoted"] and span["text"] == "我会留下"
                )
                self.assertIsNone(casefile._direct_quote_scope_error(text, quote))
                self.assertEqual(
                    "stated_position",
                    casefile.derive_claim_kind_for_span(
                        quote["text"], quote, text
                    ),
                )

    def test_reported_quote_keeps_the_outer_communication_event(self) -> None:
        text = "他发来消息说“我会留下”。"
        draft = _standard_shell(text, "round34-communication")
        communication_span = next(
            (
                span
                for span in draft["source_spans"]
                if span["quoted"] is False
                and span["text"] == "他发来消息"
            ),
            None,
        )
        self.assertIsNotNone(
            communication_span,
            "the quote must not mask the observable receipt of a message",
        )
        observation_type = casefile.derive_observation_type(
            communication_span["text"], communication_span
        )
        self.assertEqual("communication_event", observation_type)

        draft["claims"].append(
            {
                "id": "C1",
                "kind": "observable_fact",
                "observation_type": observation_type,
                "text": communication_span["text"],
                "input_id": communication_span["input_id"],
                "source_span_id": communication_span["id"],
                "source_ref": communication_span["source_ref"],
                "source_type": "user_direct_observation",
                "exact_quote": communication_span["text"],
                "epistemic_status": "reported",
                "diagnostic_boundary": False,
            }
        )
        draft["evidence"].append(
            {
                "id": "E1",
                "input_id": communication_span["input_id"],
                "source_span_id": communication_span["id"],
                "source_ref": communication_span["source_ref"],
                "source_type": "user_direct_observation",
                "exact_quote": communication_span["text"],
                "can_establish": ["C1"],
                "cannot_establish": [],
                "limitations": ["single_party_report"],
            }
        )
        draft["evidence_links"].append(
            {
                "proposition_id": "C1",
                "evidence_ref": "E1",
                "relation": "supports",
                "strength": "direct",
                "reason": "anchor_matches_report",
            }
        )
        _append_stated_position(draft, "我会留下", "C2", "E2")

        self.assertEqual([], casefile.validate_casefile(draft))
        response = casefile.render_markdown(draft)
        fact_section = response.split("## 1. 可观察事实", 1)[1].split(
            "## 1A.", 1
        )[0]
        self.assertIn("他发来消息", fact_section)
        self.assertNotIn("我会留下", fact_section)


if __name__ == "__main__":
    unittest.main()
