#!/usr/bin/env python3
"""Regression tests frozen from the independent V2 boundary review."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
GOOD = ROOT / "tests" / "fixtures" / "valid-c01.json"
ANALYSIS = ROOT / "tests" / "fixtures" / "analysis-c01.json"
CLOCK = "2026-08-06T00:00:00Z"
BASE_INPUT = "我是典型 I 人，所以我不适合带团队，也不可能做好公开表达。"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def output(result: subprocess.CompletedProcess[str]) -> dict:
    if not result.stdout.strip():
        raise AssertionError(f"missing JSON output: {result.stderr}")
    return json.loads(result.stdout)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


class RefinementPolicyTests(unittest.TestCase):
    def validate_action(self, action: str) -> tuple[int, set[str]]:
        case = json.loads(GOOD.read_text(encoding="utf-8"))
        case["analysis"]["experiment"]["action"] = action
        with tempfile.TemporaryDirectory(prefix="identity-policy-") as tmp:
            path = Path(tmp) / "case.json"
            path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
            result = run_cli("validate", str(path))
        return result.returncode, {item["code"] for item in output(result)["errors"]}

    def test_medical_change_synonyms_are_rejected(self) -> None:
        for action in (
            "暂停服用处方药七天，观察专注变化",
            "把每天两片改成每天一片，连续三天记录睡眠",
            "先不吃医生开的处方药三天，看看精神状态",
        ):
            with self.subTest(action=action):
                code, errors = self.validate_action(action)
                self.assertNotEqual(0, code)
                self.assertIn("medical_plan_change", errors)

    def test_high_cost_synonyms_are_rejected(self) -> None:
        for action in (
            "向公司提交离职申请，看看压力是否下降",
            "办理休学手续一个学期，验证我是否更适合自由学习",
            "与伴侣办理分居手续，观察一周情绪变化",
            "解除与公司的劳动合同，观察压力是否下降",
        ):
            with self.subTest(action=action):
                code, errors = self.validate_action(action)
                self.assertNotEqual(0, code)
                self.assertIn("high_cost_experiment", errors)

    def test_positive_identity_synonyms_are_rejected(self) -> None:
        for reason in (
            "这说明你其实是有潜力的领袖",
            "负面标签背后其实是高韧性人格",
            "你不是内向，只是稀缺型领导人才",
        ):
            case = json.loads(GOOD.read_text(encoding="utf-8"))
            case["analysis"]["candidate_variables"][0]["reason"] = reason
            with tempfile.TemporaryDirectory(prefix="identity-positive-") as tmp:
                path = Path(tmp) / "case.json"
                path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
                result = run_cli("validate", str(path))
            with self.subTest(reason=reason):
                self.assertNotEqual(0, result.returncode)
                self.assertIn("positive_relabel", {item["code"] for item in output(result)["errors"]})

    def test_route_cannot_be_forged_to_correct_a_stable_preference(self) -> None:
        case = json.loads(GOOD.read_text(encoding="utf-8"))
        case["evidence"][0]["text"] = "我更喜欢独处，周末一个人更舒服。"
        case["analysis"]["labels"] = []
        case["analysis"]["judgments"] = []
        with tempfile.TemporaryDirectory(prefix="identity-route-") as tmp:
            path = Path(tmp) / "case.json"
            path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
            result = run_cli("validate", str(path))
        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "preference_correction",
            {item["code"] for item in output(result)["errors"]},
        )

    def test_zero_width_character_does_not_hide_label_as_behavior(self) -> None:
        case = json.loads(GOOD.read_text(encoding="utf-8"))
        case["evidence"][0]["text"] = "内向型内向\u200b型"
        case["analysis"]["labels"] = [
            {
                "text": "内向型",
                "source_type": "user_self_description",
                "evidence_status": "reported_unverified",
                "source": {"evidence_id": "E000", "quote": "内向型", "start": 0, "end": 3},
                "attribution": {
                    "speaker": {"role": "self", "text": "", "span": {"start": 0, "end": 0}},
                    "source": {
                        "type": "user_self_description",
                        "evidence_status": "reported_unverified",
                    },
                    "predicate": {
                        "kind": "self_identifies",
                        "polarity": "affirmed",
                        "text": "",
                        "span": {"start": 0, "end": 0},
                    },
                    "target": {
                        "role": "current_user",
                        "text": "",
                        "resolution": "explicit",
                        "span": {"start": 0, "end": 0},
                    },
                    "label": {"start": 0, "end": 3},
                    "discourse_context": {
                        "kind": "personal",
                        "span": {"start": 0, "end": 7},
                    },
                },
            }
        ]
        case["analysis"]["judgments"] = []
        case["analysis"]["observations"] = [
            {
                "text": "内向\u200b型",
                "context": "unknown",
                "frequency": "unknown",
                "timeframe": "unknown",
                "source": {"evidence_id": "E000", "quote": "内向\u200b型", "start": 3, "end": 7},
            }
        ]
        with tempfile.TemporaryDirectory(prefix="identity-unicode-") as tmp:
            path = Path(tmp) / "case.json"
            path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
            result = run_cli("validate", str(path))
        self.assertNotEqual(0, result.returncode)
        self.assertIn("label_is_not_behavior", {item["code"] for item in output(result)["errors"]})


class ClinicalBoundaryRegressionTests(unittest.TestCase):
    def scaffold(self, text: str) -> dict:
        result = run_cli("scaffold", "--text", text, "--clock", CLOCK)
        self.assertEqual(0, result.returncode, result.stderr)
        return output(result)

    def test_ai_source_has_priority_over_clinical_term(self) -> None:
        for text in (
            "另一个AI说我是ADHD，所以我不可能做好公开表达。",
            "模型判断我是抑郁症，所以我永远交不了稿。",
        ):
            case = self.scaffold(text)
            with self.subTest(text=text):
                self.assertEqual(
                    {"ai_inference"},
                    {item["source_type"] for item in case["analysis"]["labels"]},
                )

    def test_suspicion_and_formal_scale_are_not_promoted_to_diagnosis(self) -> None:
        suspected = self.scaffold(
            "我怀疑自己可能有抑郁症，但我从未看过医生，也没有接受过正式诊断。请只记录这是我的怀疑。"
        )
        self.assertNotIn(
            "reported_clinical_diagnosis",
            {item["source_type"] for item in suspected["analysis"]["labels"]},
        )
        scale = self.scaffold(
            "心理师给我做了正式量表，量表结果提示ADHD风险偏高，但医生尚未给出诊断。"
        )
        self.assertEqual(
            {"formal_scale_result"},
            {item["source_type"] for item in scale["analysis"]["labels"]},
        )

    def test_severe_functional_impairment_is_not_swallowed_by_preference(self) -> None:
        case = self.scaffold(
            "我更喜欢一个人待着，但过去六周我几乎无法出门，已经缺勤十二次，也常常整天吃不下东西。我不知道该怎么办。"
        )
        self.assertEqual("support_escalation", case["route"]["mode"])
        self.assertTrue(case["risk_flags"]["functional_impairment"])
        with tempfile.TemporaryDirectory(prefix="identity-support-") as tmp:
            path = Path(tmp) / "case.json"
            path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
            rendered = run_cli("render", str(path))
        self.assertEqual(0, rendered.returncode, rendered.stderr)
        self.assertIn("现实专业支持", rendered.stdout)
        self.assertNotIn("只要努力", rendered.stdout)

    def test_medical_request_scaffold_validates_and_renders_boundary(self) -> None:
        for text in (
            "精神科医生正式诊断我为ADHD，我觉得药让我反应变慢，所以我应该马上停药吗？",
            "我有正式诊断，现在想自行换药。请直接告诉我换成哪一种和怎么调整剂量。",
        ):
            case = self.scaffold(text)
            with tempfile.TemporaryDirectory(prefix="identity-medical-") as tmp:
                path = Path(tmp) / "case.json"
                path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
                validated = run_cli("validate", str(path))
                rendered = run_cli("render", str(path))
            with self.subTest(text=text):
                self.assertEqual(0, validated.returncode, validated.stdout)
                self.assertEqual(0, rendered.returncode, rendered.stdout)
                self.assertIn("不要自行停药、换药或调整剂量", rendered.stdout)
                self.assertIn("处方", rendered.stdout)

    def test_safety_renderer_contains_real_world_actions(self) -> None:
        cases = (
            ("我有抑郁症，今晚想自杀，身边已经放着一整瓶药。", ("当地急救", "可信任", "药物")),
            ("我现在想伤害伴侣，手里已经拿着刀，我怕自己会动手。", ("当地急救", "放下", "拉开距离")),
        )
        for text, phrases in cases:
            case = self.scaffold(text)
            with tempfile.TemporaryDirectory(prefix="identity-safety-") as tmp:
                path = Path(tmp) / "case.json"
                path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
                rendered = run_cli("render", str(path))
            with self.subTest(text=text):
                self.assertEqual(0, rendered.returncode, rendered.stdout)
                for phrase in phrases:
                    self.assertIn(phrase, rendered.stdout)

    def test_empty_input_and_bad_json_use_stable_errors(self) -> None:
        empty = run_cli("scaffold", "--text", "", "--clock", CLOCK)
        self.assertNotEqual(0, empty.returncode)
        self.assertIn("input_empty", {item["code"] for item in output(empty)["errors"]})
        with tempfile.TemporaryDirectory(prefix="identity-json-") as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not-json", encoding="utf-8")
            bad = run_cli("validate", str(path))
        self.assertNotEqual(0, bad.returncode)
        self.assertIn("json_decode_error", {item["code"] for item in output(bad)["errors"]})


class ReplaySemanticsRegressionTests(unittest.TestCase):
    def create_started_case(self, case_dir: Path) -> None:
        confirmation_file = case_dir.parent / f"{case_dir.name}-confirmation.txt"
        confirmation_file.write_text("我确认按当前小实验开始。\n", encoding="utf-8")
        commands = (
            ("init", "--text", BASE_INPUT, "--case-dir", str(case_dir), "--clock", CLOCK),
            ("plan", "--case-dir", str(case_dir), "--analysis", str(ANALYSIS), "--clock", "2026-08-06T00:01:00Z"),
            (
                "start", "--case-dir", str(case_dir),
                "--confirmation-file", str(confirmation_file),
                "--clock", "2026-08-06T00:02:00Z",
            ),
        )
        for command in commands:
            result = run_cli(*command)
            self.assertEqual(0, result.returncode, f"{command}: {result.stdout} {result.stderr}")

    def test_event_tail_rollback_is_detected_by_monotonic_head(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-head-") as tmp:
            case_dir = Path(tmp) / "case"
            self.create_started_case(case_dir)
            head_path = case_dir / "events.head.json"
            self.assertTrue(head_path.is_file())
            lines = (case_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
            previous = json.loads(lines[-2])
            (case_dir / "events.jsonl").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
            (case_dir / "case.json").write_text(
                json.dumps(previous["snapshot"], ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            replay = run_cli("replay", "--case-dir", str(case_dir))
            self.assertNotEqual(0, replay.returncode)
            self.assertIn("event_chain_truncated", {item["code"] for item in output(replay)["errors"]})

    def test_rehashed_event_type_still_must_match_state_transition(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-event-") as tmp:
            case_dir = Path(tmp) / "case"
            self.create_started_case(case_dir)
            events_path = case_dir / "events.jsonl"
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            events[1]["type"] = "start"
            previous_hash = None
            for event in events:
                event["previous_event_sha256"] = previous_hash
                event["snapshot_sha256"] = digest(event["snapshot"])
                event["event_sha256"] = digest({key: value for key, value in event.items() if key != "event_sha256"})
                previous_hash = event["event_sha256"]
            events_path.write_text(
                "\n".join(json.dumps(event, ensure_ascii=False, sort_keys=True) for event in events) + "\n",
                encoding="utf-8",
            )
            head_path = case_dir / "events.head.json"
            head = json.loads(head_path.read_text(encoding="utf-8"))
            head["latest_event_sha256"] = events[-1]["event_sha256"]
            head_path.write_text(json.dumps(head, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            replay = run_cli("replay", "--case-dir", str(case_dir))
            self.assertNotEqual(0, replay.returncode)
            self.assertIn("event_transition_mismatch", {item["code"] for item in output(replay)["errors"]})


if __name__ == "__main__":
    unittest.main()
