from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round116CorrectiveQuoteScopeRedTests(unittest.TestCase):
    """Keep affirmative correction and explicit exclusion opposite in polarity."""

    def _stated_quotes(self, text: str) -> list[str]:
        return [
            str(span["text"])
            for span in casefile.generate_source_spans("I1", text)
            if casefile.derive_claim_kind_for_span(
                str(span["text"]), span, text
            )
            == "stated_position"
        ]

    def test_erfei_exclusion_cannot_become_a_second_stated_position(self) -> None:
        text = "他说的是“我会留下”，而非“我会离开”。"
        self.assertEqual(
            ["我会留下"],
            self._stated_quotes(text),
            "而非 explicitly excludes its following quotation; it is not an "
            "affirmative correction scope.",
        )

    def test_ershi_correction_still_opens_an_affirmative_position(self) -> None:
        text = "他没有说“我会离开”，而是说“我会留下”。"
        self.assertEqual(["我会留下"], self._stated_quotes(text))


if __name__ == "__main__":
    unittest.main()
