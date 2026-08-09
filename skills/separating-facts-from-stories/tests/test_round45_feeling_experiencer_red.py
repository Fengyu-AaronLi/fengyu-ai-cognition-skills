from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
from test_round39_semantic_scope_red import (  # noqa: E402
    anchored_explicit_feeling_case,
)


class Round45FeelingExperiencerRedTests(unittest.TestCase):
    """RED regressions: attribution about the user is not user self-report."""

    def test_external_cognition_prediction_or_denial_is_not_user_feeling(self) -> None:
        texts = (
            "他以为我很难过。",
            "她猜我很焦虑。",
            "老板断定我很失望。",
            "模型预测我很焦虑。",
            "他否认我很难过。",
        )
        for index, text in enumerate(texts, start=1):
            with self.subTest(text=text):
                self.assertFalse(casefile.is_explicit_feeling(text))
                draft = anchored_explicit_feeling_case(
                    text, f"round45-attributed-feeling-{index}"
                )
                self.assertIn(
                    "CLAIM_KIND_MISMATCH",
                    {item["code"] for item in casefile.validate_casefile(draft)},
                )

    def test_direct_user_experience_forms_remain_available(self) -> None:
        texts = (
            "今天我很焦虑。",
            "一想到这件事我很焦虑。",
            "他没回消息，所以我很难过。",
            "这件事让我很失望。",
            "我因为这件事很焦虑。",
        )
        for text in texts:
            with self.subTest(text=text):
                self.assertTrue(casefile.is_explicit_feeling(text))


if __name__ == "__main__":
    unittest.main()
