#!/usr/bin/env python3
"""R77 red contracts promoted from discovery probes D002, D006, and D009."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "identity_label_case.py"
CLOCK = "2026-08-07T00:00:00Z"


SPEC = importlib.util.spec_from_file_location("identity_label_runtime_v77", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load identity label runtime")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def scaffold(text: str) -> dict:
    return MODULE.scaffold_case(text, None, CLOCK)


def nonpersonal_observation(case: dict) -> tuple[str, bool, list[dict]]:
    return (
        case["route"]["mode"],
        case["route"]["trigger"],
        case["analysis"]["labels"],
    )


class DiscoveryScopeAndNonpersonalContracts(unittest.TestCase):
    def test_d002_friend_quote_is_not_routed_as_the_current_users_case(self) -> None:
        case = scaffold(
            "〔探针02〕朋友说：‘我被另一个 AI 叫作慢热型，所以一定做不好主持跨部门会议。’"
            "这是他的原话，不是我的情况。"
        )
        self.assertEqual(
            ("needs_information", False, []),
            nonpersonal_observation(case),
        )

    def test_d006_term_explanation_does_not_retain_a_personal_label(self) -> None:
        case = scaffold(
            "〔探针06〕请解释社交媒体上“慢热型”通常指什么；"
            "这不是对我的描述，也不要替我判断人格。"
        )
        self.assertEqual(
            ("needs_information", False, []),
            nonpersonal_observation(case),
        )

    def test_d009_glossary_question_does_not_retain_a_personal_label(self) -> None:
        case = scaffold(
            "〔探针09〕我在整理术语表：典型 I 人和行为描述有什么区别？"
            "没有提供任何个人案例。"
        )
        self.assertEqual(
            ("needs_information", False, []),
            nonpersonal_observation(case),
        )


if __name__ == "__main__":
    unittest.main()
