from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
CASEFILE_PATH = SKILL_DIR / "scripts" / "casefile.py"
SPEC = importlib.util.spec_from_file_location(
    "round127_safety_feeling_casefile", CASEFILE_PATH
)
assert SPEC is not None and SPEC.loader is not None
casefile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(casefile)


class SafetyFeelingBlindTests(unittest.TestCase):
    def test_third_party_self_harm_is_not_reassigned_to_user(self) -> None:
        cases = (
            "朋友现在告诉我，他打算今晚自杀。",
            "朋友发消息说：\u201c我不想活了。\u201d",
            "朋友发消息说：\u201c我并非不想自杀。\u201d",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    {"third_party_self_harm_risk"},
                    casefile.expected_safety_signal_types(text),
                )

    def test_explicit_first_person_reaction_feeling_is_recognized(self) -> None:
        text = "她发完消息后，我反而安心了。"
        spans = casefile.generate_source_spans("I1", text)
        self.assertTrue(
            any(
                casefile._is_current_user_explicit_feeling(
                    span["text"], span, text
                )
                for span in spans
            )
        )


if __name__ == "__main__":
    unittest.main()
