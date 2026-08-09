#!/usr/bin/env python3
"""V33 red contracts: a result page is a source, not automatically quoted prose."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "identity_label_case.py"
SPEC = importlib.util.spec_from_file_location("identity_label_runtime_v33", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load identity label runtime")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
CLOCK = "2026-08-06T00:00:00Z"


class SocialPageProvenanceTests(unittest.TestCase):
    def test_result_page_labels_are_social_labels(self) -> None:
        cases = (
            ("昨晚在公众号做了一个三分钟 ADHD 网测，页面说高分，所以我注定做不了长期项目。", "ADHD"),
            ("昨晚在公众号做了一个三分钟 ADHD 网测，页面说我是高敏感者。", "高敏感者"),
            ("页面说我是回避型。", "回避型"),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                case = MODULE.scaffold_case(text, None, CLOCK)
                labels = {
                    item["text"]: item["source_type"]
                    for item in case["analysis"]["labels"]
                }
                self.assertEqual("social_media_label", labels.get(expected), case["analysis"])

    def test_explicit_page_quotation_remains_context_only(self) -> None:
        case = MODULE.scaffold_case("页面写“我是回避型”，这里只是引用。", None, CLOCK)
        self.assertNotIn("回避型", [item["text"] for item in case["analysis"]["labels"]])
        quoted = [
            item for item in case["analysis"]["context_claims"]
            if item["claim"] == "回避型"
        ]
        self.assertEqual(1, len(quoted), case["analysis"])
        self.assertEqual("quoted_material", quoted[0]["source"])


if __name__ == "__main__":
    unittest.main()
