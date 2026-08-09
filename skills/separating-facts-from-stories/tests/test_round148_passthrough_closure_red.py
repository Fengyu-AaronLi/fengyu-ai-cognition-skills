from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402
import workflow  # noqa: E402


class Round148PassthroughClosureRedTests(unittest.TestCase):
    def test_formatting_plus_epistemic_second_task_routes_standard(self) -> None:
        for text in (
            "整理：老板说他会开除我；看看这是不是实话。",
            "整理：老板说他会开除我；确认一下消息靠不靠谱。",
            "整理：老板说他会开除我；查一下是否可信。",
            "整理：老板说他会开除我；告诉我这话能不能信。",
            "整理：老板说他会开除我；分析一下这话的来路。",
            "整理：老板说他会开除我；看看他到底想干嘛。",
        ):
            with self.subTest(text=text):
                self.assertIsNone(casefile.parse_pure_transform_task(text), text)
                self.assertEqual(
                    "standard",
                    casefile.make_draft(text, "round148-route", "auto")["mode"],
                )

    def test_formatting_response_cannot_add_new_epistemic_story(self) -> None:
        request = "整理：老板说他会开除我。"
        for response in (
            "老板说他会开除我。他这么说是想吓唬你。",
            "老板说他会开除我。他显然不喜欢你。",
            "老板说他会开除我。这句话的来源可信。",
        ):
            with self.subTest(response=response):
                valid, errors = workflow.validate_passthrough_response(
                    "formatting", request, response
                )
                self.assertFalse(valid, response)
                self.assertIn("epistemic_content_added", errors)

    def test_faithful_formatting_control_remains_passthrough(self) -> None:
        request = "整理：老板说他会开除我。"
        parsed = casefile.parse_pure_transform_task(request)
        self.assertEqual(
            {"kind": "formatting", "payload": "老板说他会开除我。"}, parsed
        )
        self.assertEqual(
            (True, []),
            workflow.validate_passthrough_response(
                "formatting", request, "老板说他会开除我。"
            ),
        )


if __name__ == "__main__":
    unittest.main()
