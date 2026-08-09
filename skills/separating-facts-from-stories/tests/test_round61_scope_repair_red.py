from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
import workflow  # noqa: E402
from test_round19_semantic_lifecycle_red import _standard_shell  # noqa: E402
from test_round37_semantic_truthfulness_red import _append_fact  # noqa: E402


def _append_feeling(draft: dict, exact_quote: str) -> None:
    span = next(
        item
        for item in draft["source_spans"]
        if item["input_id"] == draft["current_input_id"]
        and item["text"] == exact_quote
    )
    draft["claims"].append(
        {
            "id": "C1",
            "kind": "explicit_feeling",
            "text": exact_quote,
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "explicit_self_report",
            "exact_quote": exact_quote,
            "epistemic_status": "reported",
            "diagnostic_boundary": False,
        }
    )
    draft["evidence"].append(
        {
            "id": "E1",
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "explicit_self_report",
            "exact_quote": exact_quote,
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


class Round61ScopeRepairRedTests(unittest.TestCase):
    """Black-box scope failures found after the Round60 release candidate."""

    def test_negated_translation_intent_cannot_hide_a_current_threat(self) -> None:
        text = "这不是翻译：他现在真的堵在门外说要杀我。"

        self.assertIn(
            "explicit_threat", casefile.expected_safety_signal_types(text)
        )
        self.assertTrue(casefile.detect_immediate_risk(text))
        self.assertIsNone(workflow.classify_passthrough_request(text))

    def test_resolved_or_negated_threat_is_not_current_but_recurrence_is(self) -> None:
        resolved = (
            "昨天他曾威胁要杀我，但警方已到场，危险已经解除。",
            "去年他说要杀我，案件已结案，现在没有现实风险。",
            "他没有威胁要杀我，只是让我翻译这句话。",
        )
        for text in resolved:
            with self.subTest(kind="resolved", text=text):
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))
                self.assertFalse(casefile.detect_immediate_risk(text))

        recurrent = (
            "昨天他曾威胁要杀我，但警方已到场，危险已经解除，今晚他又威胁要杀我。",
            "去年他说要杀我，案件已结案，但他此刻又堵在门外。",
            "他没有威胁要杀我，但今晚他又威胁要杀我。",
        )
        for text in recurrent:
            with self.subTest(kind="recurrent", text=text):
                self.assertIn(
                    "explicit_threat", casefile.expected_safety_signal_types(text)
                )
                self.assertTrue(casefile.detect_immediate_risk(text))

    def test_pure_translation_scope_is_position_robust_but_mixed_help_is_safety(self) -> None:
        pure_translations = (
            "翻译成英文：他现在在门外说要杀我。",
            "他现在在门外说要杀我，翻译成英文。",
            "请把他现在在门外说要杀我翻译成英文。",
            "他现在在门外说要杀我，请翻译。",
            "将“我想伤害自己”译为英语。",
        )
        for text in pure_translations:
            with self.subTest(kind="pure", text=text):
                self.assertEqual(
                    "translation", workflow.classify_passthrough_request(text)
                )
                self.assertFalse(workflow.passthrough_has_mixed_intent(text))
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))

        mixed_requests = (
            "我现在有危险，他堵在门外，先帮我翻译一条求助消息。",
            "他此刻堵在门外说要杀我，先帮我翻译一条求助消息。",
        )
        for text in mixed_requests:
            with self.subTest(kind="mixed", text=text):
                self.assertIn(
                    "explicit_threat", casefile.expected_safety_signal_types(text)
                )
                self.assertTrue(workflow.passthrough_has_mixed_intent(text))
                self.assertIsNone(workflow.classify_passthrough_request(text))

    def test_current_user_feeling_forms_are_supported_without_upgrading_propositions(self) -> None:
        supported = (
            ("我感到手心出汗。", "我感到手心出汗。"),
            (
                "我明确感到害怕，但不知道他为什么没回。",
                "我明确感到害怕，",
            ),
            ("我的感受是委屈。", "我的感受是委屈。"),
        )
        for index, (text, feeling_span) in enumerate(supported, start=1):
            with self.subTest(kind="supported", text=text):
                self.assertTrue(casefile.is_explicit_feeling(feeling_span))
                draft = _standard_shell(text, f"round61-feeling-{index}")
                _append_feeling(draft, feeling_span)
                self.assertEqual([], casefile.validate_casefile(draft))

        interpretation = "我感到他在撒谎"
        span = casefile.generate_source_spans("I1", interpretation)[0]
        self.assertFalse(casefile.is_explicit_feeling(interpretation))
        self.assertEqual(
            "interpretation",
            casefile.derive_claim_kind_for_span(interpretation, span, interpretation),
        )

        for text in ("他感到害怕。", "医生说，我感到害怕。"):
            with self.subTest(kind="third_party", text=text):
                self.assertFalse(casefile.is_explicit_feeling(text))

    def test_explicit_correction_blocks_old_fact_and_keeps_new_event_auditable(self) -> None:
        text = "他没有参加会议。纠正一下，他参加了。"
        spans = casefile.generate_source_spans("I1", text)
        old_span = next(item for item in spans if item["text"] == "他没有参加会议。")
        new_span = next(item for item in spans if item["text"] == "他参加了。")

        self.assertTrue(
            casefile._has_unconsumed_decisive_observation_correction(text, old_span)
        )
        self.assertEqual(
            "participation_or_schedule_event",
            casefile.derive_observation_type(new_span["text"], new_span),
        )

        old_as_fact = _standard_shell(text, "round61-correction-old")
        _append_fact(old_as_fact, "他没有参加会议。", "C1", "E1")
        self.assertIn(
            "OBSERVATION_CORRECTION_UNCONSUMED",
            {item["code"] for item in casefile.validate_casefile(old_as_fact)},
        )

        corrected_as_fact = _standard_shell(text, "round61-correction-new")
        self.assertEqual(
            ["他没有参加会议。"],
            [
                item["exact_quote"]
                for item in corrected_as_fact["unclassified_observation_candidates"]
            ],
        )
        _append_fact(corrected_as_fact, "他参加了。", "C1", "E1")
        self.assertEqual([], casefile.validate_casefile(corrected_as_fact))


if __name__ == "__main__":
    unittest.main()
