#!/usr/bin/env python3
"""V61 contract: suggested messages cannot invent the user's inner state."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UnreportedMessageContentTests(unittest.TestCase):
    def test_skill_forbids_inventing_feelings_or_motives_in_message_templates(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(
            "建议消息不得替用户填入未报告的感受、动机或保证",
            skill,
        )
        self.assertIn("占位符", skill)
        self.assertIn("确认属实", skill)


if __name__ == "__main__":
    unittest.main()
