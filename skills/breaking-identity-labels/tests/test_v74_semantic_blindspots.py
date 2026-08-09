#!/usr/bin/env python3
"""R74 red contracts for uncovered identity-label semantic blind spots."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "identity_label_case.py"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-c01.json"
CLOCK = "2026-08-07T08:00:00Z"


SPEC = importlib.util.spec_from_file_location("identity_label_runtime_v74", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load identity label runtime")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def scaffold(text: str) -> dict:
    return MODULE.scaffold_case(text, None, CLOCK)


def claim_triplets(case: dict) -> set[tuple[str, str, str]]:
    return {
        (item["claim"], item["subject"], item["polarity"])
        for item in case["analysis"]["context_claims"]
    }


class NegationAndQuotedMaterialBlindSpots(unittest.TestCase):
    def test_chinese_negative_identity_synonyms_are_not_promoted_to_labels(self) -> None:
        for text in (
            "我绝非回避型，只是这两天没回消息。",
            "我谈不上是回避型，只是这两天没回消息。",
        ):
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual([], case["analysis"]["labels"])
                self.assertIn(
                    ("回避型", "current_user", "negated"),
                    claim_triplets(case),
                )

    def test_chinese_uncertain_identity_synonyms_are_not_promoted_to_labels(self) -> None:
        for text in (
            "我不见得是回避型，只是这两天没回消息。",
            "我未必是回避型，只是这两天没回消息。",
        ):
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual([], case["analysis"]["labels"])
                self.assertIn(
                    ("回避型", "current_user", "uncertain"),
                    claim_triplets(case),
                )

    def test_ai_uncertainty_is_context_not_an_affirmed_ai_label(self) -> None:
        case = scaffold("AI未必认为我是回避型。")
        self.assertEqual([], case["analysis"]["labels"])
        claims = {
            (item["claim"], item["subject"], item["polarity"], item["source"])
            for item in case["analysis"]["context_claims"]
        }
        self.assertIn(
            ("回避型", "current_user", "uncertain", "ai_inference"),
            claims,
        )

    def test_ai_rewrite_quote_for_proofreading_is_not_personal_label_evidence(self) -> None:
        case = scaffold("AI把这句话写成“我是回避型”，请只校对引号里的文本。")
        self.assertEqual([], case["analysis"]["labels"])
        self.assertFalse(case["route"]["trigger"])


class SubjectAndClinicalScopeBlindSpots(unittest.TestCase):
    def test_possessive_first_person_does_not_steal_mothers_reflexive_label(self) -> None:
        case = scaffold("我母亲说她自己是回避型，所以她不可能经营好关系。")
        self.assertEqual([], case["analysis"]["labels"])
        self.assertIn(
            ("回避型", "third_party", "affirmed"),
            claim_triplets(case),
        )

    def test_arbitrary_named_third_party_verdict_is_not_bound_to_current_user(self) -> None:
        case = scaffold("同事陈雯说自己是回避型，所以陈雯不适合带团队。")
        self.assertEqual([], case["analysis"]["labels"])
        self.assertEqual([], case["analysis"]["judgments"])

    def test_formal_diagnosis_does_not_swallow_colloquial_capability_verdict(self) -> None:
        case = scaffold("我有医生正式诊断的 ADHD，所以重要项目还是别让我负责。")
        self.assertEqual("deconstruct", case["route"]["mode"])
        self.assertIn("diagnosis_to_global_verdict", case["route"]["reason_codes"])
        self.assertTrue(
            any(
                item["kind"] == "capability_verdict"
                and "别让我负责" in item["text"]
                for item in case["analysis"]["judgments"]
            )
        )


class PreferenceAndFunctionScopeBlindSpots(unittest.TestCase):
    def test_disliked_problem_behavior_is_not_recast_as_a_stable_preference(self) -> None:
        case = scaffold(
            "我不喜欢自己每周都迟交工作，这个月已经导致三次逾期，"
            "我想改变这个行为。"
        )
        self.assertNotEqual("preference_acknowledgement", case["route"]["mode"])
        self.assertNotEqual("no_intervention", case["status"])

    def test_past_preference_functioning_does_not_mask_current_severe_impairment(self) -> None:
        case = scaffold(
            "我不喜欢大型聚会，平时能正常上班、看医生和买东西。"
            "但最近一个月连床都下不了，工作全部停了。"
        )
        self.assertEqual("support_escalation", case["route"]["mode"])
        self.assertTrue(case["risk_flags"]["functional_impairment"])
        self.assertIn(
            "reported_severe_functional_impairment",
            case["route"]["reason_codes"],
        )


class ExperimentFalsifiabilityBlindSpots(unittest.TestCase):
    def setUp(self) -> None:
        self.case = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual([], MODULE.validate_case(self.case))

    def codes_for(self, support_if: list[str], weaken_if: list[str]) -> set[str]:
        case = copy.deepcopy(self.case)
        case["analysis"]["experiment"]["support_if"] = support_if
        case["analysis"]["experiment"]["weaken_if"] = weaken_if
        return {item["code"] for item in MODULE.validate_case(case)}

    def test_one_outcome_cannot_appear_on_both_sides_of_the_experiment(self) -> None:
        codes = self.codes_for(
            ["在固定十五分钟准备后仍未完成团队更新"],
            [
                "在固定十五分钟准备后仍未完成团队更新",
                "按时完成更新且听众能够复述主要信息",
            ],
        )
        self.assertIn("experiment_not_falsifiable", codes)

    def test_semantically_equivalent_noncompletion_outcomes_are_not_opposites(self) -> None:
        codes = self.codes_for(
            ["在固定十五分钟准备后仍未完成团队更新"],
            ["在固定十五分钟准备后没有完成团队更新"],
        )
        self.assertIn("experiment_not_falsifiable", codes)


if __name__ == "__main__":
    unittest.main()
