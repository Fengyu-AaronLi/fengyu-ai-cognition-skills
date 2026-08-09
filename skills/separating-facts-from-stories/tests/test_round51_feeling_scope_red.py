from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
from test_round37_semantic_truthfulness_red import (  # noqa: E402
    _explicit_feeling_case,
)
from test_round39_semantic_scope_red import (  # noqa: E402
    anchored_explicit_feeling_case,
)


class Round51FeelingScopeRedTests(unittest.TestCase):
    """RED regressions: bind a feeling to its actual experiencer and source."""

    def assert_external_attribution_is_not_user_feeling(
        self, text: str, case_id: str
    ) -> None:
        draft = anchored_explicit_feeling_case(text, case_id)
        span = next(
            item
            for item in draft["source_spans"]
            if item["input_id"] == draft["current_input_id"]
            and any(marker in item["text"] for marker in ("难过", "焦虑", "失望"))
        )
        self.assertFalse(
            casefile._is_current_user_explicit_feeling(span["text"], span, text)
        )
        self.assertIn(
            "CLAIM_KIND_MISMATCH",
            {item["code"] for item in casefile.validate_casefile(draft)},
        )

    def assert_direct_user_feeling_is_allowed(self, text: str, case_id: str) -> None:
        self.assertTrue(casefile.is_explicit_feeling(text))
        draft = _explicit_feeling_case(text, case_id)
        self.assertNotIn(
            "CLAIM_KIND_MISMATCH",
            {item["code"] for item in casefile.validate_casefile(draft)},
        )

    def test_clinician_observation_is_external_attribution(self) -> None:
        self.assert_external_attribution_is_not_user_feeling(
            "据医生观察，我很焦虑。", "round51-clinician-attribution"
        )

    def test_family_report_is_external_attribution(self) -> None:
        self.assert_external_attribution_is_not_user_feeling(
            "我姐说，我很焦虑。", "round51-family-attribution"
        )

    def test_other_person_perspective_is_external_attribution(self) -> None:
        self.assert_external_attribution_is_not_user_feeling(
            "她断言，至少在她看来，我很焦虑。",
            "round51-other-perspective-attribution",
        )

    def test_artifact_report_is_external_attribution(self) -> None:
        self.assert_external_attribution_is_not_user_feeling(
            "报告写道，我很焦虑。", "round51-artifact-attribution"
        )

    def test_recurring_time_adjunct_preserves_direct_feeling(self) -> None:
        self.assert_direct_user_feeling_is_allowed(
            "每次开会前我都很焦虑。", "round51-recurring-time-adjunct"
        )

    def test_event_time_adjunct_preserves_direct_feeling(self) -> None:
        self.assert_direct_user_feeling_is_allowed(
            "回到家以后我很难过。", "round51-event-time-adjunct"
        )

    def test_situational_adjunct_preserves_direct_feeling(self) -> None:
        self.assert_direct_user_feeling_is_allowed(
            "面对老板时我很害怕。", "round51-situational-adjunct"
        )


if __name__ == "__main__":
    unittest.main()
