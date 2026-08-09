from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round50PostfixTruthScopeRedTests(unittest.TestCase):
    """A later clause that revokes an event must keep the event out of facts."""

    def assert_no_observable_span(self, text: str) -> None:
        observed = [
            item["text"]
            for item in casefile.generate_source_spans("I1", text)
            if casefile.derive_observation_type(item["text"], item) is not None
        ]
        self.assertEqual([], observed)

    def test_anaphoric_invention_revokes_prior_event(self) -> None:
        self.assert_no_observable_span("他没回消息，这事是我瞎编的。")

    def test_anaphoric_fabrication_revokes_prior_event(self) -> None:
        self.assert_no_observable_span("老板取消了会议，这件事纯属杜撰。")

    def test_later_verification_of_nonoccurrence_revokes_prior_event(self) -> None:
        self.assert_no_observable_span("老板取消了会议，经核实并未发生。")

    def test_waking_from_dream_revokes_prior_event(self) -> None:
        self.assert_no_observable_span("他没回消息，醒来才知道是梦。")

    def test_later_debunking_revokes_prior_event(self) -> None:
        self.assert_no_observable_span("老板取消了会议，后来这条消息被辟谣。")

    def test_anaphoric_authorship_of_unrelated_object_keeps_event(self) -> None:
        observed = [
            item["text"]
            for item in casefile.generate_source_spans(
                "I1", "他没回消息，这个提醒文案是我写的。"
            )
            if casefile.derive_observation_type(item["text"], item) is not None
        ]
        self.assertIn(
            "他没回消息",
            [item.rstrip("，,。；;") for item in observed],
        )


if __name__ == "__main__":
    unittest.main()
