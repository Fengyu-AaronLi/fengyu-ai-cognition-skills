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
from test_round37_semantic_truthfulness_red import (  # noqa: E402
    _append_fact,
    _explicit_feeling_case,
)
from test_round33_candidate_lifecycle_red import (  # noqa: E402
    add_candidate_only_completion_fields,
)


class Round58SemanticRoutingRedTests(unittest.TestCase):
    """Paired context regressions left by the Round55 black-box review."""

    def test_resolved_historical_threat_is_not_current_but_recurrence_is(self) -> None:
        resolved = (
            "十年前他说过“我要杀你”，现在没有威胁。",
            "十年前他说过“我要杀你”。警方已处理，现在我很安全。",
            "十年前他说过“我要杀你”，当事人已去世且不可能接近。",
        )
        for text in resolved:
            with self.subTest(text=text):
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))
                self.assertFalse(casefile.detect_immediate_risk(text))

        recurrent = (
            "十年前他说过“我要杀你”，警方当时处理过，但他现在又在门外。",
            "十年前他说过“我要杀你”。警方已处理，我曾经很安全，"
            "但他今晚又发来“我要杀你”。",
        )
        for text in recurrent:
            with self.subTest(text=text):
                self.assertIn(
                    "explicit_threat",
                    casefile.expected_safety_signal_types(text),
                )
                self.assertTrue(casefile.detect_immediate_risk(text))

    def test_propositional_feeling_body_experience_and_schedule_are_distinct(self) -> None:
        interpretation = "我感到他在撒谎。"
        interpretation_span = casefile.generate_source_spans(
            "I1", interpretation
        )[0]
        self.assertFalse(casefile.is_explicit_feeling(interpretation))
        self.assertEqual(
            "interpretation",
            casefile.derive_claim_kind_for_span(
                interpretation,
                interpretation_span,
                interpretation,
            ),
        )

        for index, text in enumerate(
            ("我胸口发紧。", "我感觉胸口发紧。"), start=1
        ):
            with self.subTest(text=text):
                draft = _explicit_feeling_case(text, f"round58-body-{index}")
                self.assertEqual([], casefile.validate_casefile(draft))
                span = draft["source_spans"][0]
                self.assertIsNone(
                    casefile.derive_claim_kind_for_span(text, span, text)
                )

        scheduled = "会议定在明天下午三点。"
        scheduled_span = casefile.generate_source_spans("I1", scheduled)[0]
        self.assertEqual(
            "participation_or_schedule_event",
            casefile.derive_observation_type(scheduled, scheduled_span),
        )

        future_plan = "我明天会参加会议。"
        future_span = casefile.generate_source_spans("I1", future_plan)[0]
        self.assertIsNone(casefile.derive_observation_type(future_plan, future_span))

    def test_decisive_postfix_correction_cannot_be_silently_ignored(self) -> None:
        corrected = "我亲眼看到她删除了文件，但后来发现那只是回收站预览。"
        pending = casefile.make_draft(
            corrected, "round58-corrected-pending", "standard"
        )
        self.assertEqual(
            ["我亲眼看到她删除了文件，"],
            [
                item["exact_quote"]
                for item in pending["unclassified_observation_candidates"]
            ],
        )
        add_candidate_only_completion_fields(pending)
        self.assertEqual([], casefile.validate_casefile(pending))

        draft = _standard_shell(corrected, "round58-corrected-observation")
        _append_fact(draft, "我亲眼看到她删除了文件，", "C1", "E1")
        codes = {item["code"] for item in casefile.validate_casefile(draft)}
        self.assertIn("OBSERVATION_CORRECTION_UNCONSUMED", codes)

        ordinary_followup = "我亲眼看到她删除了文件，后来她关闭了电脑。"
        control = _standard_shell(ordinary_followup, "round58-ordinary-followup")
        _append_fact(control, "我亲眼看到她删除了文件，", "C1", "E1")
        self.assertEqual([], casefile.validate_casefile(control))

    def test_translation_passthrough_is_position_robust_without_bypass(self) -> None:
        translations = (
            "请翻译成英文：“我要杀你”",
            "“我要杀你”，翻译成英文",
            "翻译：“你好”",
            "翻译：你好",
            "请翻译“你好”。",
            "小说角色说“我要杀你”，请翻译成英文",
        )
        for text in translations:
            with self.subTest(text=text):
                self.assertEqual(
                    "translation", workflow.classify_passthrough_request(text)
                )
                self.assertFalse(workflow.passthrough_has_mixed_intent(text))

        mixed = "先分析他为什么不爱我，再把这句话翻译成英文。"
        self.assertIsNone(workflow.classify_passthrough_request(mixed))
        self.assertTrue(workflow.passthrough_has_mixed_intent(mixed))

        immediate = "他现在持刀在我门外，请把这句话翻译成英文。"
        self.assertIsNone(workflow.classify_passthrough_request(immediate))
        self.assertTrue(workflow.passthrough_has_mixed_intent(immediate))
        self.assertIn(
            "explicit_threat", casefile.expected_safety_signal_types(immediate)
        )


if __name__ == "__main__":
    unittest.main()
