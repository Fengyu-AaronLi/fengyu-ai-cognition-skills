#!/usr/bin/env python3
"""Frozen V12 attribution contracts from the independent pre-audit blockers.

These cases preserve the 24 P0/P1 inputs reported in
``evals/raw/v2-forward/v12-preaudit/attribution/report.md``.  The tests group
cases by semantic mechanism while retaining every original case id and input.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
CLOCK = "2026-08-07T01:00:00Z"


BLOCKER_CASES = {
    "AT-004-A": "你觉得我是不是回避型？",
    "AT-004-B": "你觉得小李是不是回避型？",
    "AT-005-B": "你就是拖延症，别拿我举例。",
    "AT-007-A": "是我内向，不是他内向。",
    "AT-007-B": "不是我内向，是他内向。",
    "AT-013-A": "医生确认我有抑郁症。",
    "AT-018-A": "不是我自己说我是回避型，是AI给出的结论。",
    "AT-018-B": "不是AI说我是回避型，是我自己这么说的。",
    "AT-019-A": "抖音测试说我是I人。",
    "AT-019-B": "公司正式MBTI施测报告显示我是I型。",
    "AT-020-A": "热门帖子说我两天没回消息，所以我是回避型。",
    "AT-021-B": "临床医生完整评估后诊断妹妹有边缘型人格障碍。",
    "AT-025-B": "安静办公是我的宿命，我不可能适应任何会议。",
    "AT-026-B": "我周末不社交，所以我天生冷漠，所有关系都不会长久。",
    "AT-027-B": "我每天独处两小时恢复精力，所以任何团队工作都不适合我。",
    "AT-030-A": "我在2025年完成正式MBTI施测，结果是INTJ。",
    "AT-030-B": "我在2025年完成正式MBTI施测，结果是INTJ，所以我天生不适合销售。",
    "AT-036-B": '请校验JSON：{"message":"我就是个失败者，永远不会成功。"}',
    "AT-037-B": "这是小说角色台词：‘我就是个失败者，永远不会成功。’",
    "AT-038-B": "翻译：‘医生诊断我有ADHD，所以我没救了。’",
    "AT-044-B": "请回复小李：‘我是回避型。’这里的‘我’是小李。",
    "AT-045-A": "临床医生对我说：‘你有ADHD。’",
    "AT-046-B": '分析这段JSON：{"message":"我是INTJ，所以当不了主管。"}',
    "AT-052-B": "我让AI改写句子‘我是回避型’，它没有在评价我。",
}

EXPECTED_CASE_IDS = {
    "AT-004-A",
    "AT-004-B",
    "AT-005-B",
    "AT-007-A",
    "AT-007-B",
    "AT-013-A",
    "AT-018-A",
    "AT-018-B",
    "AT-019-A",
    "AT-019-B",
    "AT-020-A",
    "AT-021-B",
    "AT-025-B",
    "AT-026-B",
    "AT-027-B",
    "AT-030-A",
    "AT-030-B",
    "AT-036-B",
    "AT-037-B",
    "AT-038-B",
    "AT-044-B",
    "AT-045-A",
    "AT-046-B",
    "AT-052-B",
}


def scaffold(case_id: str) -> dict:
    text = BLOCKER_CASES[case_id]
    result = subprocess.run(
        [sys.executable, str(CLI), "scaffold", "--text", text, "--clock", CLOCK],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"{case_id}: {result.stdout}{result.stderr}")
    return json.loads(result.stdout)


def labels(case: dict) -> list[dict]:
    return case["analysis"]["labels"]


def current_user_labels(case: dict) -> list[dict]:
    return [
        item
        for item in labels(case)
        if item.get("attribution", {}).get("target", {}).get("role") == "current_user"
    ]


def current_user_affirmed_labels(case: dict) -> list[dict]:
    return [
        item
        for item in current_user_labels(case)
        if item.get("attribution", {}).get("predicate", {}).get("polarity") == "affirmed"
    ]


def source_types(case: dict) -> set[str]:
    return {item["source_type"] for item in current_user_labels(case)}


class V12PreAttributionBlockers(unittest.TestCase):
    def test_frozen_inventory_contains_every_reported_p0_p1_case(self) -> None:
        self.assertEqual(EXPECTED_CASE_IDS, set(BLOCKER_CASES))
        self.assertEqual(24, len(BLOCKER_CASES))
        self.assertTrue(all(BLOCKER_CASES.values()))

    def test_nonpersonal_material_forms_do_not_become_current_user_state(self) -> None:
        case_ids = (
            "AT-036-B",
            "AT-037-B",
            "AT-038-B",
            "AT-044-B",
            "AT-046-B",
            "AT-052-B",
        )
        for case_id in case_ids:
            with self.subTest(case_id=case_id, text=BLOCKER_CASES[case_id]):
                case = scaffold(case_id)
                self.assertIn("nonpersonal_material", case["route"]["reason_codes"])
                self.assertFalse(case["route"]["trigger"])
                self.assertFalse(case["risk_flags"]["clinical"])
                self.assertEqual([], current_user_labels(case))
                self.assertEqual([], case["analysis"]["judgments"])

    def test_explicit_third_party_and_contrast_targets_are_not_reassigned(self) -> None:
        third_party_only = ("AT-004-B", "AT-005-B", "AT-021-B")
        for case_id in third_party_only:
            with self.subTest(case_id=case_id, text=BLOCKER_CASES[case_id]):
                case = scaffold(case_id)
                self.assertEqual([], current_user_labels(case))
                for item in labels(case):
                    self.assertIn(
                        item["attribution"]["target"]["role"],
                        {"third_party", "unresolved"},
                    )

        with self.subTest(case_id="AT-007-A", text=BLOCKER_CASES["AT-007-A"]):
            current_user_affirmed = scaffold("AT-007-A")
            affirmed = current_user_affirmed_labels(current_user_affirmed)
            self.assertTrue(affirmed, BLOCKER_CASES["AT-007-A"])
            self.assertTrue(all(item["source_type"] == "user_self_description" for item in affirmed))

        with self.subTest(case_id="AT-007-B", text=BLOCKER_CASES["AT-007-B"]):
            current_user_negated = scaffold("AT-007-B")
            self.assertEqual([], current_user_affirmed_labels(current_user_negated))
            for item in labels(current_user_negated):
                if item["attribution"]["predicate"]["polarity"] == "affirmed":
                    self.assertEqual("third_party", item["attribution"]["target"]["role"])

    def test_local_source_anchors_preserve_request_clinical_social_and_scale_status(self) -> None:
        with self.subTest(case_id="AT-004-A", text=BLOCKER_CASES["AT-004-A"]):
            request = scaffold("AT-004-A")
            request_labels = current_user_labels(request)
            self.assertEqual([], request_labels, BLOCKER_CASES["AT-004-A"])
            self.assertEqual("needs_information", request["route"]["mode"])
            claims = [
                item
                for item in request["analysis"]["context_claims"]
                if item["claim"] == "回避型"
            ]
            self.assertEqual(1, len(claims))
            self.assertEqual("current_user", claims[0]["subject"])
            self.assertEqual("unknown_source", claims[0]["source"])
            self.assertEqual("uncertain", claims[0]["polarity"])

        expected_sources = {
            "AT-013-A": "reported_clinical_diagnosis",
            "AT-018-A": "ai_inference",
            "AT-018-B": "user_self_description",
            "AT-019-A": "social_media_label",
            "AT-019-B": "formal_scale_result",
            "AT-020-A": "social_media_label",
            "AT-030-A": "formal_scale_result",
            "AT-030-B": "formal_scale_result",
            "AT-045-A": "reported_clinical_diagnosis",
        }
        for case_id, expected_source in expected_sources.items():
            with self.subTest(
                case_id=case_id,
                text=BLOCKER_CASES[case_id],
                expected_source=expected_source,
            ):
                case = scaffold(case_id)
                self.assertIn(expected_source, source_types(case))
                if expected_source == "reported_clinical_diagnosis":
                    self.assertTrue(case["risk_flags"]["clinical"])
                if case_id in {"AT-018-A", "AT-018-B"}:
                    self.assertTrue(current_user_affirmed_labels(case))

    def test_preference_plus_global_verdict_is_retained_for_deconstruction(self) -> None:
        expected_judgment_fragments = {
            "AT-025-B": "不可能适应任何会议",
            "AT-026-B": "所有关系都不会长久",
            "AT-027-B": "任何团队工作都不适合我",
        }
        for case_id, expected_fragment in expected_judgment_fragments.items():
            with self.subTest(
                case_id=case_id,
                text=BLOCKER_CASES[case_id],
                expected_fragment=expected_fragment,
            ):
                case = scaffold(case_id)
                self.assertEqual("deconstruct", case["route"]["mode"])
                judgments = case["analysis"]["judgments"]
                self.assertTrue(judgments)
                self.assertTrue(any(expected_fragment in item["text"] for item in judgments))


if __name__ == "__main__":
    unittest.main()
