from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round44EventDisavowalScopeRedTests(unittest.TestCase):
    """RED regressions: a later truth-status tail scopes the event before it."""

    def assert_no_observable_span(self, text: str) -> None:
        spans = casefile.generate_source_spans("I1", text)
        observed = [
            (item["text"], casefile.derive_observation_type(item["text"], item))
            for item in spans
            if casefile.derive_observation_type(item["text"], item) is not None
        ]
        self.assertEqual(
            [],
            observed,
            "a proposition explicitly withdrawn as invented, false, imagined, or dreamed cannot survive as an observable fact span",
        )

    def test_postfixed_first_person_invention_revokes_the_event(self) -> None:
        self.assert_no_observable_span("他没回消息其实是我编的。")

    def test_postfixed_false_message_revokes_the_event(self) -> None:
        self.assert_no_observable_span("老板取消了会议其实是假消息。")

    def test_postfixed_imagination_revokes_the_event(self) -> None:
        self.assert_no_observable_span("他已读消息六小时没回是我想象的。")

    def test_postfixed_dream_scope_revokes_the_event(self) -> None:
        self.assert_no_observable_span("我没有完成计划只是梦里的情节。")

    def test_later_discovery_of_misreport_revokes_the_event(self) -> None:
        self.assert_no_observable_span("老板取消了会议，不过我后来发现是误传。")

    def test_postfixed_joke_scope_revokes_the_event(self) -> None:
        self.assert_no_observable_span("老板取消了会议其实只是个玩笑。")

    def test_disavowal_does_not_hide_a_later_reality_reset(self) -> None:
        text = "他没回消息其实是我编的。回到现实，他今天没回消息。"
        observed = [
            item["text"]
            for item in casefile.generate_source_spans("I1", text)
            if casefile.derive_observation_type(item["text"], item) is not None
        ]
        self.assertEqual(["他今天没回消息。"], observed)

    def test_unrelated_first_person_authorship_does_not_revoke_the_event(self) -> None:
        text = "他没回消息，但我编了一个新的提醒文案。"
        observed = [
            item["text"]
            for item in casefile.generate_source_spans("I1", text)
            if casefile.derive_observation_type(item["text"], item) is not None
        ]
        self.assertIn("他没回消息", [item.rstrip("，,。；;") for item in observed])


if __name__ == "__main__":
    unittest.main()
