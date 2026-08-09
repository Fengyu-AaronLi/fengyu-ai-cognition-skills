from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
from test_round19_semantic_lifecycle_red import (  # noqa: E402
    _span,
    _standard_shell,
)
from test_round37_semantic_truthfulness_red import _append_fact  # noqa: E402
from test_round39_semantic_scope_red import (  # noqa: E402
    add_retraction_transition,
    first_story,
)


def append_story(
    draft: dict, quote: str, kind: str, claim_id: str, evidence_id: str
) -> None:
    span = _span(draft, quote)
    draft["claims"].append(
        {
            "id": claim_id,
            "kind": kind,
            "text": quote,
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "user_report",
            "exact_quote": quote,
            "epistemic_status": "unverified",
            "diagnostic_boundary": False,
        }
    )
    draft["evidence"].append(
        {
            "id": evidence_id,
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "user_report",
            "exact_quote": quote,
            "can_establish": [],
            "cannot_establish": [claim_id],
            "limitations": ["single_party_report"],
        }
    )
    draft["evidence_links"].append(
        {
            "proposition_id": claim_id,
            "evidence_ref": evidence_id,
            "relation": "does_not_establish",
            "strength": "none",
            "reason": "source_scope_limit",
        }
    )


class Round47RetractionBindingRedTests(unittest.TestCase):
    def codes_without_retraction(self, first: dict, text: str, case_id: str) -> set[str]:
        second = casefile.start_update(first, text)
        _append_fact(second, "老板今天取消了会议。", "C9", "E9")
        return {
            item["code"]
            for item in casefile.validate_casefile(second, previous=first)
        }

    def test_nested_negation_does_not_retract_the_embedded_story(self) -> None:
        first = first_story("round47-nested-negation")
        text = "我不再认为他在架空我是不可能的。老板今天取消了会议。"
        codes = self.codes_without_retraction(first, text, "unused")
        self.assertNotIn("RETRACTED_STORY_STATUS_NOT_UPDATED", codes)

        second = casefile.start_update(first, text)
        _append_fact(second, "老板今天取消了会议。", "C2", "E2")
        add_retraction_transition(second)
        self.assertIn(
            "RETRACTION_NOT_EXPLICIT",
            {item["code"] for item in casefile.validate_casefile(second, previous=first)},
        )

    def test_ambiguous_topic_cannot_retract_multiple_active_stories(self) -> None:
        first = _standard_shell(
            "我认为他在架空我。我觉得他不爱我。",
            "round47-ambiguous-topic",
        )
        append_story(first, "我认为他在架空我。", "interpretation", "C1", "E1")
        append_story(first, "我觉得他不爱我。", "motive_inference", "C2", "E2")
        self.assertEqual([], casefile.validate_casefile(first))

        codes = self.codes_without_retraction(
            first,
            "我撤回关于他的判断。老板今天取消了会议。",
            "unused",
        )
        self.assertNotIn("RETRACTED_STORY_STATUS_NOT_UPDATED", codes)

    def test_explicit_third_party_ownership_exclusion_does_not_retract_user_story(self) -> None:
        first = first_story("round47-third-party-owner")
        text = (
            "我撤回之前转述的他的判断而不是我自己的解释。"
            "老板今天取消了会议。"
        )
        codes = self.codes_without_retraction(first, text, "unused")
        self.assertNotIn("RETRACTED_STORY_STATUS_NOT_UPDATED", codes)

        second = casefile.start_update(first, text)
        _append_fact(second, "老板今天取消了会议。", "C2", "E2")
        add_retraction_transition(second)
        self.assertIn(
            "RETRACTION_NOT_EXPLICIT",
            {item["code"] for item in casefile.validate_casefile(second, previous=first)},
        )


if __name__ == "__main__":
    unittest.main()
