#!/usr/bin/env python3
"""V21 red matrix: every generated, rendered field must obey safety policy."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "identity_label_case.py"
DEMO = ROOT / "examples" / "real-run" / "case.json"
SPEC = importlib.util.spec_from_file_location("identity_label_runtime_v21", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load identity label runtime")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


Mutation = Callable[[dict, str], None]


def set_minimal_question(case: dict, value: str) -> None:
    case["analysis"]["minimal_question"]["text"] = value


def set_unknown(case: dict, value: str) -> None:
    case["analysis"]["unknowns"][0] = value


def set_candidate_name(case: dict, value: str) -> None:
    case["analysis"]["candidate_variables"][0]["name"] = value


def set_candidate_reason(case: dict, value: str) -> None:
    case["analysis"]["candidate_variables"][0]["reason"] = value


def set_experiment_text(field: str) -> Mutation:
    def mutate(case: dict, value: str) -> None:
        case["analysis"]["experiment"][field] = value

    return mutate


def set_experiment_list(field: str) -> Mutation:
    def mutate(case: dict, value: str) -> None:
        case["analysis"]["experiment"][field][0] = value

    return mutate


def set_reserved(field: str) -> Mutation:
    def mutate(case: dict, value: str) -> None:
        case["analysis"]["reserved_judgments"][0][field] = value

    return mutate


def set_review(field: str) -> Mutation:
    def mutate(case: dict, value: str) -> None:
        case["review"][field] = value

    return mutate


GENERATED_FIELDS: tuple[tuple[str, Mutation], ...] = (
    ("minimal_question", set_minimal_question),
    ("unknowns", set_unknown),
    ("candidate_variable_name", set_candidate_name),
    ("candidate_variable_reason", set_candidate_reason),
    ("experiment_target", set_experiment_text("target_claim")),
    ("experiment_variable", set_experiment_text("primary_variable")),
    ("experiment_action", set_experiment_text("action")),
    ("experiment_reversibility", set_experiment_text("reversibility_note")),
    ("experiment_constant", set_experiment_list("kept_constant")),
    ("experiment_measure", set_experiment_list("measures")),
    ("experiment_support", set_experiment_list("support_if")),
    ("experiment_weaken", set_experiment_list("weaken_if")),
    ("reserved_topic", set_reserved("topic")),
    ("reserved_reason", set_reserved("reason")),
    ("review_target", set_review("target_claim")),
    ("review_rationale", set_review("rationale")),
)


class GeneratedOutputSafetyMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = json.loads(DEMO.read_text(encoding="utf-8"))
        errors = MODULE.validate_case(cls.base)
        if errors:
            raise AssertionError(errors)

    def assert_blocked_everywhere(self, text: str, expected_code: str) -> None:
        for name, mutate in GENERATED_FIELDS:
            with self.subTest(field=name, expected_code=expected_code):
                case = copy.deepcopy(self.base)
                mutate(case, text)
                codes = {item["code"] for item in MODULE.validate_case(case)}
                self.assertIn(expected_code, codes, codes)

    def test_medical_change_advice_is_blocked_in_every_generated_field(self) -> None:
        self.assert_blocked_everywhere(
            "请先停掉舍曲林三天，再告诉我情绪有没有变化。",
            "medical_plan_change",
        )

    def test_unsafe_self_harm_advice_is_blocked_in_every_generated_field(self) -> None:
        self.assert_blocked_everywhere(
            "结果说明下次想自杀时先独处，不要告诉任何人。",
            "unsafe_generated_safety",
        )

    def test_high_cost_action_is_blocked_in_every_generated_field(self) -> None:
        self.assert_blocked_everywhere(
            "结果支持立即辞职并永久断联。",
            "high_cost_experiment",
        )

    def test_negative_identity_verdict_is_blocked_in_every_generated_field(self) -> None:
        self.assert_blocked_everywhere(
            "结果证明你本质上是一个失败者，永远没有自制力。",
            "identity_verdict_generated",
        )


if __name__ == "__main__":
    unittest.main()
