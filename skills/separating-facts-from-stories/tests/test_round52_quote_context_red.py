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


class Round52QuoteContextRedTests(unittest.TestCase):
    """RED regressions: context outranks a human-looking name around a quote."""

    def codes_for_position(self, text: str, case_id: str) -> set[str]:
        draft = _standard_shell(text, case_id)
        _append_stated_position(draft, "我会留下", "C1", "E1")
        return {item["code"] for item in casefile.validate_casefile(draft)}

    def test_artifact_with_person_name_is_not_a_current_speech_act(self) -> None:
        codes = self.codes_for_position(
            "墓碑上的张先生写道“我会留下”。", "round52-named-artifact"
        )
        self.assertTrue(
            {"DIRECT_QUOTE_NOT_ASSERTED", "DIRECT_QUOTE_PROVENANCE_UNKNOWN"}
            & codes,
            codes,
        )

    def test_virtual_character_with_person_name_is_not_current_speaker(self) -> None:
        codes = self.codes_for_position(
            "虚拟角色张先生今天说“我会留下”。", "round52-named-virtual-character"
        )
        self.assertTrue(
            {"DIRECT_QUOTE_NOT_ASSERTED", "DIRECT_QUOTE_PROVENANCE_UNKNOWN"}
            & codes,
            codes,
        )

    def test_previous_occasion_quote_is_not_current(self) -> None:
        self.assertIn(
            "DIRECT_QUOTE_NOT_CURRENT",
            self.codes_for_position(
                "上次老板说“我会留下”。", "round52-previous-occasion"
            ),
        )

    def test_postfixed_three_year_scope_is_not_current(self) -> None:
        self.assertIn(
            "DIRECT_QUOTE_NOT_CURRENT",
            self.codes_for_position(
                "他说“我会留下”，这是三年前的原话。",
                "round52-postfixed-three-years",
            ),
        )

    def test_mother_is_a_supported_current_human_speaker(self) -> None:
        self.assertEqual(
            set(),
            self.codes_for_position(
                "妈妈今天说“我会留下”。", "round52-current-mother"
            ),
        )

    def test_father_is_a_supported_current_human_speaker(self) -> None:
        self.assertEqual(
            set(),
            self.codes_for_position(
                "父亲现在说“我会留下”。", "round52-current-father"
            ),
        )


if __name__ == "__main__":
    unittest.main()
