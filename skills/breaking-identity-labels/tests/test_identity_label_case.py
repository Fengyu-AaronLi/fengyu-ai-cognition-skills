#!/usr/bin/env python3
"""Executable acceptance tests for breaking-identity-labels V2."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "identity_label_case.py"
FIXTURES = ROOT / "tests" / "fixtures"
TEST_TMP = ROOT / "tests" / ".tmp"
FIXED_CLOCK = "2026-08-05T00:00:00Z"
C01 = "我是典型 I 人，所以我不适合带团队，也不可能做好公开表达。"
C03 = "我有正式 ADHD 诊断，所以我做不好长期项目。"
C04 = "我喜欢安静房间工作，不喜欢大型聚会。"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def parsed_stdout(result: subprocess.CompletedProcess[str]) -> dict:
    if not result.stdout.strip():
        raise AssertionError(
            f"CLI did not emit JSON; exit={result.returncode}; stderr={result.stderr.strip()}"
        )
    return json.loads(result.stdout)


class RuntimePackageTests(unittest.TestCase):
    def test_package_contains_runtime_assets_not_only_prompts(self) -> None:
        required = [
            SCRIPT,
            ROOT / "schemas" / "case.schema.json",
            ROOT / "schemas" / "analysis.schema.json",
            ROOT / "schemas" / "event.schema.json",
            ROOT / "templates" / "analysis.json",
            ROOT / "docs" / "quickstart.md",
            ROOT / "docs" / "acceptance.md",
            ROOT / "SOURCE_OF_TRUTH.md",
            ROOT / "Makefile",
        ]
        self.assertEqual([], [str(path) for path in required if not path.is_file()])

    def test_scaffold_routes_identity_verdict_and_keeps_source_spans(self) -> None:
        result = run_cli(
            "scaffold",
            "--text",
            C01,
            "--case-id",
            "test-c01",
            "--clock",
            FIXED_CLOCK,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        case = parsed_stdout(result)
        self.assertEqual("deconstruct", case["route"]["mode"])
        self.assertTrue(case["route"]["trigger"])
        self.assertEqual("I 人", case["analysis"]["labels"][0]["text"])
        source = case["analysis"]["labels"][0]["source"]
        evidence = case["evidence"][0]["text"]
        self.assertEqual(source["quote"], evidence[source["start"] : source["end"]])
        self.assertIn("capability_verdict", {item["kind"] for item in case["analysis"]["judgments"]})

    def test_stable_preference_routes_to_no_intervention(self) -> None:
        result = run_cli("scaffold", "--text", C04, "--clock", FIXED_CLOCK)
        self.assertEqual(0, result.returncode, result.stderr)
        case = parsed_stdout(result)
        self.assertEqual("preference_acknowledgement", case["route"]["mode"])
        self.assertFalse(case["route"]["trigger"])
        self.assertEqual("no_intervention", case["status"])
        self.assertEqual("not_needed", case["analysis"]["experiment"]["status"])
        self.assertEqual([], case["analysis"]["labels"])

    def test_formal_diagnosis_is_preserved_but_verdict_is_separate(self) -> None:
        result = run_cli("scaffold", "--text", C03, "--clock", FIXED_CLOCK)
        self.assertEqual(0, result.returncode, result.stderr)
        case = parsed_stdout(result)
        label = case["analysis"]["labels"][0]
        self.assertEqual("reported_clinical_diagnosis", label["source_type"])
        self.assertEqual("user_reported_formal_diagnosis", label["evidence_status"])
        self.assertTrue(case["risk_flags"]["clinical"])
        self.assertEqual("deconstruct", case["route"]["mode"])
        self.assertIn("我做不好长期项目", [item["text"] for item in case["analysis"]["judgments"]])


class PolicyGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.good = json.loads((FIXTURES / "valid-c01.json").read_text(encoding="utf-8"))
        TEST_TMP.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        for path in TEST_TMP.glob("policy-*.json"):
            path.unlink()

    def validate_mutation(self, name: str, mutate) -> tuple[subprocess.CompletedProcess[str], dict]:
        data = copy.deepcopy(self.good)
        mutate(data)
        path = TEST_TMP / f"policy-{name}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        result = run_cli("validate", str(path))
        return result, parsed_stdout(result)

    def test_valid_case_passes_schema_and_policy(self) -> None:
        result = run_cli("validate", str(FIXTURES / "valid-c01.json"))
        self.assertEqual(0, result.returncode, result.stderr)
        payload = parsed_stdout(result)
        self.assertTrue(payload["valid"])
        self.assertEqual([], payload["errors"])

    def test_missing_required_field_is_rejected_by_schema(self) -> None:
        result, payload = self.validate_mutation("schema", lambda data: data.pop("route"))
        self.assertNotEqual(0, result.returncode)
        self.assertIn("schema_required", {error["code"] for error in payload["errors"]})

    def test_fabricated_source_span_is_rejected(self) -> None:
        def mutate(data: dict) -> None:
            data["analysis"]["labels"][0]["source"]["start"] = 0

        result, payload = self.validate_mutation("span", mutate)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("source_span_mismatch", {error["code"] for error in payload["errors"]})

    def test_label_cannot_be_smuggled_in_as_behavior(self) -> None:
        def mutate(data: dict) -> None:
            data["analysis"]["observations"] = [
                {
                    "text": "I 人",
                    "context": "unknown",
                    "frequency": "unknown",
                    "timeframe": "unknown",
                    "source": {
                        "evidence_id": "E000",
                        "quote": "I 人",
                        "start": 5,
                        "end": 8
                    }
                }
            ]

        result, payload = self.validate_mutation("label-as-behavior", mutate)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("label_is_not_behavior", {error["code"] for error in payload["errors"]})

    def test_medical_change_cannot_be_an_experiment(self) -> None:
        def mutate(data: dict) -> None:
            data["analysis"]["experiment"]["action"] = "停药七天观察能否完成项目"

        result, payload = self.validate_mutation("medical", mutate)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("medical_plan_change", {error["code"] for error in payload["errors"]})

    def test_high_cost_decision_cannot_be_an_experiment(self) -> None:
        def mutate(data: dict) -> None:
            data["analysis"]["experiment"]["action"] = "今晚辞职并永久关停项目"

        result, payload = self.validate_mutation("high-cost", mutate)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("high_cost_experiment", {error["code"] for error in payload["errors"]})

    def test_positive_relabel_is_rejected(self) -> None:
        def mutate(data: dict) -> None:
            data["analysis"]["minimal_question"]["text"] = "你是否其实是隐藏型领导者？"

        result, payload = self.validate_mutation("positive-relabel", mutate)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("positive_relabel", {error["code"] for error in payload["errors"]})

    def test_preference_case_cannot_receive_correction_experiment(self) -> None:
        result = run_cli("scaffold", "--text", C04, "--clock", FIXED_CLOCK)
        case = parsed_stdout(result)
        case["status"] = "planned"
        case["analysis"] = copy.deepcopy(self.good["analysis"])
        path = TEST_TMP / "policy-preference.json"
        path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        validated = run_cli("validate", str(path))
        payload = parsed_stdout(validated)
        self.assertNotEqual(0, validated.returncode)
        self.assertIn("preference_correction", {error["code"] for error in payload["errors"]})


class RenderingAndStateTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        self.case_dir = TEST_TMP / "lifecycle-case"
        self.confirmation_file = TEST_TMP / "lifecycle-confirmation.txt"
        self.confirmation_file.write_text("我确认按当前小实验开始。\n", encoding="utf-8")
        if self.case_dir.exists():
            for path in sorted(self.case_dir.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            self.case_dir.rmdir()

    def tearDown(self) -> None:
        if self.case_dir.exists():
            for path in sorted(self.case_dir.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            self.case_dir.rmdir()
        if self.confirmation_file.exists():
            self.confirmation_file.unlink()

    def test_render_is_generated_from_validated_structured_case(self) -> None:
        result = run_cli("render", str(FIXTURES / "valid-c01.json"))
        self.assertEqual(0, result.returncode, result.stderr)
        for number in range(1, 11):
            self.assertIn(f"{number}.", result.stdout)
        self.assertIn("I 人", result.stdout)
        self.assertIn("E000", result.stdout)

    def test_full_lifecycle_is_replayable_and_revisioned(self) -> None:
        commands = [
            (
                "init",
                "--text",
                C01,
                "--case-dir",
                str(self.case_dir),
                "--case-id",
                "lifecycle-c01",
                "--clock",
                "2026-08-05T00:00:00Z",
            ),
            (
                "plan",
                "--case-dir",
                str(self.case_dir),
                "--analysis",
                str(FIXTURES / "analysis-c01.json"),
                "--clock",
                "2026-08-05T00:01:00Z",
            ),
            (
                "start",
                "--case-dir",
                str(self.case_dir),
                "--confirmation-file",
                str(self.confirmation_file),
                "--clock",
                "2026-08-05T00:02:00Z",
            ),
            (
                "record",
                "--case-dir",
                str(self.case_dir),
                "--kind",
                "experiment_result",
                "--source-text",
                "今天在十五分钟准备后完成了三分钟团队更新，听众能复述两点。",
                "--fact",
                "完成了三分钟团队更新",
                "--context",
                "团队周会",
                "--timeframe",
                "今天",
                "--clock",
                "2026-08-12T00:03:00Z",
            ),
            (
                "review",
                "--case-dir",
                str(self.case_dir),
                "--classification",
                "weakens",
                "--rationale",
                "本次在固定准备时间下完成了目标行为，只能削弱该窄命题。",
                "--clock",
                "2026-08-12T00:04:00Z",
            ),
        ]
        for command in commands:
            result = run_cli(*command)
            self.assertEqual(0, result.returncode, f"{command}: {result.stderr}")

        replay = run_cli("replay", "--case-dir", str(self.case_dir))
        self.assertEqual(0, replay.returncode, replay.stderr)
        replay_payload = parsed_stdout(replay)
        self.assertTrue(replay_payload["valid"])
        self.assertEqual(5, replay_payload["event_count"])
        self.assertEqual(4, replay_payload["latest_revision"])

        status = run_cli("status", "--case-dir", str(self.case_dir))
        status_payload = parsed_stdout(status)
        self.assertEqual("reviewed", status_payload["status"])
        self.assertEqual("weakens", status_payload["classification"])
        self.assertEqual(4, status_payload["revision"])

        report_path = self.case_dir / "report.md"
        rendered = run_cli(
            "render",
            str(self.case_dir / "case.json"),
            "--out",
            str(report_path),
        )
        self.assertEqual(0, rendered.returncode, rendered.stderr)
        self.assertTrue(report_path.is_file())
        self.assertIn("只能削弱该窄命题", report_path.read_text(encoding="utf-8"))

    def test_replay_detects_tampering(self) -> None:
        init = run_cli(
            "init",
            "--text",
            C01,
            "--case-dir",
            str(self.case_dir),
            "--case-id",
            "tamper-c01",
            "--clock",
            FIXED_CLOCK,
        )
        self.assertEqual(0, init.returncode, init.stderr)
        events = self.case_dir / "events.jsonl"
        event = json.loads(events.read_text(encoding="utf-8").splitlines()[0])
        event["snapshot"]["case_id"] = "silently-rewritten"
        events.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")
        replay = run_cli("replay", "--case-dir", str(self.case_dir))
        self.assertNotEqual(0, replay.returncode)
        self.assertIn("event_hash_mismatch", {e["code"] for e in parsed_stdout(replay)["errors"]})


if __name__ == "__main__":
    unittest.main()
