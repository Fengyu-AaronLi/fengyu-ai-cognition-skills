from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
from test_round37_semantic_truthfulness_red import _append_fact  # noqa: E402
from test_round39_semantic_scope_red import (  # noqa: E402
    add_retraction_transition,
    first_story,
)


class Round53RetractionPolarityRedTests(unittest.TestCase):
    """RED regressions: only one affirmative, uniquely bound withdrawal may act."""

    def assert_not_an_explicit_retraction(self, text: str, case_id: str) -> None:
        first = first_story(case_id)
        second = casefile.start_update(first, text)
        _append_fact(second, "老板今天取消了会议。", "C2", "E2")
        unchanged_codes = {
            item["code"]
            for item in casefile.validate_casefile(second, previous=first)
        }
        self.assertNotIn("RETRACTED_STORY_STATUS_NOT_UPDATED", unchanged_codes)

        add_retraction_transition(second)
        changed_codes = {
            item["code"]
            for item in casefile.validate_casefile(second, previous=first)
        }
        self.assertIn("RETRACTION_NOT_EXPLICIT", changed_codes)

    def test_negated_embedded_evaluation_does_not_retract_story(self) -> None:
        self.assert_not_an_explicit_retraction(
            "我不再认为他在架空我是错的。老板今天取消了会议。",
            "round53-negated-embedded-evaluation",
        )

    def test_inability_to_retract_is_not_completed_retraction(self) -> None:
        self.assert_not_an_explicit_retraction(
            "我撤回不了之前的判断。老板今天取消了会议。",
            "round53-retraction-inability",
        )

    def test_longest_unique_story_match_wins_over_substring_story(self) -> None:
        active_stories = [
            {
                "id": "C1",
                "kind": "interpretation",
                "exact_quote": "我认为他在架空我。",
                "epistemic_status": "unverified",
            },
            {
                "id": "C2",
                "kind": "prediction",
                "exact_quote": "我认为他在架空我并准备开掉我。",
                "epistemic_status": "unverified",
            },
        ]
        self.assertEqual(
            {"C2"},
            casefile._story_retraction_targets(
                "我撤回我认为他在架空我并准备开掉我的判断。",
                active_stories,
            ),
        )


if __name__ == "__main__":
    unittest.main()
