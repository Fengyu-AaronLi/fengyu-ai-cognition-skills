#!/usr/bin/env python3
"""V20 red contracts for quoted identity claims inside mixed-subject inputs."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
CLOCK = "2026-08-06T00:00:00Z"


def scaffold(text: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(CLI), "scaffold", "--text", text, "--clock", CLOCK],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


class QuotedMaterialScopeTests(unittest.TestCase):
    def assert_quoted_only(self, text: str, label: str) -> None:
        case = scaffold(text)
        self.assertNotIn(label, [item["text"] for item in case["analysis"]["labels"]])
        matches = [
            item
            for item in case["analysis"]["context_claims"]
            if item.get("claim") == label
        ]
        self.assertEqual(1, len(matches), case["analysis"])
        self.assertEqual("quoted_material", matches[0]["source"])
        self.assertNotEqual("deconstruct", case["route"]["mode"])

    def test_article_quote_is_not_promoted_after_a_third_party_diagnosis(self) -> None:
        case = scaffold("医生说我姐姐有 ADHD，但我没有；文章里写“我是回避型”。")
        self.assertEqual([], case["analysis"]["labels"])
        claims = case["analysis"]["context_claims"]
        self.assertEqual({"ADHD", "回避型"}, {item["claim"] for item in claims})
        quoted = next(item for item in claims if item["claim"] == "回避型")
        self.assertEqual("quoted_material", quoted["source"])

    def test_common_document_frames_remain_context_only(self) -> None:
        cases = (
            ("帖子里写着“我是高敏感”，这里只是引用。", "高敏感"),
            ("论文中写道“我是回避型”，请核对这句引文。", "回避型"),
            ("文章作者写“我是低能量”，这不是我的自述。", "低能量"),
        )
        for text, label in cases:
            with self.subTest(text=text):
                self.assert_quoted_only(text, label)

    def test_explicitly_owned_current_self_quote_remains_a_user_label(self) -> None:
        case = scaffold("我本人当时说“我是回避型”，而且我现在仍认可这个自述。")
        self.assertIn("回避型", [item["text"] for item in case["analysis"]["labels"]])


if __name__ == "__main__":
    unittest.main()
