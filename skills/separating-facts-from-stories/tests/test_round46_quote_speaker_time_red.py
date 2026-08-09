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


class Round46QuoteSpeakerTimeRedTests(unittest.TestCase):
    """RED regressions: current positions require human and current provenance."""

    def codes_for_position(self, text: str, case_id: str) -> set[str]:
        draft = _standard_shell(text, case_id)
        _append_stated_position(draft, "我会留下", "C1", "E1")
        return {item["code"] for item in casefile.validate_casefile(draft)}

    def test_nonreal_or_nonhuman_quote_owner_is_not_a_current_person(self) -> None:
        texts = (
            "梦里的角色说“我会留下”。",
            "合同写道“我会留下”。",
            "谣言说“我会留下”。",
            "墓碑写道“我会留下”。",
            "聊天记录写道“我会留下”。",
        )
        for index, text in enumerate(texts, start=1):
            with self.subTest(text=text):
                codes = self.codes_for_position(text, f"round46-owner-{index}")
                self.assertTrue(
                    {"DIRECT_QUOTE_NOT_ASSERTED", "DIRECT_QUOTE_PROVENANCE_UNKNOWN"}
                    & codes,
                    codes,
                )

    def test_generic_past_scope_is_not_a_current_position(self) -> None:
        texts = (
            "他当年说“我会留下”。",
            "他退休时说“我会留下”。",
            "回忆中他说“我会留下”。",
        )
        for index, text in enumerate(texts, start=1):
            with self.subTest(text=text):
                self.assertIn(
                    "DIRECT_QUOTE_NOT_CURRENT",
                    self.codes_for_position(text, f"round46-past-{index}"),
                )

    def test_positive_human_current_speakers_remain_supported(self) -> None:
        texts = (
            "他现在说“我会留下”。",
            "老板今天说“我会留下”。",
        )
        for index, text in enumerate(texts, start=1):
            with self.subTest(text=text):
                self.assertEqual(
                    set(),
                    self.codes_for_position(text, f"round46-current-{index}"),
                )


if __name__ == "__main__":
    unittest.main()
