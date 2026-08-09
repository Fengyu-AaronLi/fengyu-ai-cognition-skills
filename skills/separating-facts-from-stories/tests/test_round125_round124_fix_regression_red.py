import importlib.util
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
CASEFILE_SCRIPT = SKILL_DIR / "scripts" / "casefile.py"


def load_casefile():
    spec = importlib.util.spec_from_file_location(
        "round125_round124_fix_regression_casefile", CASEFILE_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Round124FixRegressionRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.casefile = load_casefile()

    def test_reported_user_risk_is_not_reassigned_to_the_reporter(self):
        self.assertEqual(
            {"self_harm_risk"},
            self.casefile.expected_safety_signal_types(
                "朋友说我现在想跳楼。"
            ),
        )

    def test_third_party_pronouns_remain_third_party(self):
        for text in (
            "朋友说他现在想跳楼。",
            "朋友说她现在想跳楼。",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    {"third_party_self_harm_risk"},
                    self.casefile.expected_safety_signal_types(text),
                )

    def test_negated_third_party_jump_report_is_not_promoted_to_risk(self):
        for text in (
            "朋友说他现在不想跳楼。",
            "朋友发来消息：\u201c我现在不想跳楼\u201d。",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    set(), self.casefile.expected_safety_signal_types(text)
                )

    def test_nonhuman_and_proxy_quotes_do_not_become_direct_human_speech(self):
        cases = (
            "系统发来消息：\u201c我现在想跳楼\u201d。",
            "我转发朋友的消息：\u201c我现在想跳楼\u201d。",
        )
        for text in cases:
            quote_range = self.casefile._actual_quote_ranges(text)[0]
            with self.subTest(text=text):
                self.assertEqual(
                    "unknown",
                    self.casefile._quoted_speaker_role(text, *quote_range),
                )

    def test_reaction_bridge_does_not_absorb_other_experiencers_or_pretense(self):
        cases = (
            "同事说我听完很难过。",
            "同事说，我听完很难过。",
            "同事说老板取消了会议，她听完很难过。",
            "他以为我听完很难过。",
            "我听完假装很难过。",
            "[同事转述：] 我听完很难过。",
        )
        for text in cases:
            spans = self.casefile.generate_source_spans("I1", text)
            with self.subTest(text=text):
                self.assertFalse(
                    any(
                        self.casefile._is_current_user_explicit_feeling(
                            span["text"], span, text
                        )
                        for span in spans
                    )
                )

    def test_finite_first_person_reaction_bridges_are_supported(self):
        for text in (
            "我听完很难过。",
            "我看完很难过。",
            "我读完很难过。",
            "我得知后很难过。",
            "我收到消息后很难过。",
        ):
            spans = self.casefile.generate_source_spans("I1", text)
            with self.subTest(text=text):
                self.assertTrue(
                    any(
                        self.casefile._is_current_user_explicit_feeling(
                            span["text"], span, text
                        )
                        for span in spans
                    )
                )


if __name__ == "__main__":
    unittest.main()
