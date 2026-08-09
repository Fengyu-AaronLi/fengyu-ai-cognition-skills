#!/usr/bin/env python3
"""R70 semantic fuzz contracts found after the R67 and R69 matrices passed."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "identity_label_case.py"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-c01.json"
INIT_CLOCK = "2026-08-07T04:00:00Z"
PLAN_CLOCK = "2026-08-07T04:01:00Z"
MIXED_PREFERENCE_TEXT = (
    "我喜欢安静房间工作，不喜欢大型聚会，所以我不适合带团队，"
    "也不可能做好公开表达。"
)


SPEC = importlib.util.spec_from_file_location("identity_label_runtime_v70", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load identity label runtime")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    if not result.stdout.strip():
        raise AssertionError(f"missing JSON output: {result.stderr}")
    return json.loads(result.stdout)


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class ImmediateSafetySemanticFuzz(unittest.TestCase):
    def test_bilingual_direct_harm_and_ingestion_route_to_safety(self) -> None:
        direct = (
            "I am going to end my life tonight. The gun is loaded beside me.",
            "我准备去死。安眠药在床头。",
            "我马上要杀了他。枪在兜里。",
            "我刚吞了半瓶安眠药。",
        )
        for text in direct:
            with self.subTest(text=text):
                case = MODULE.scaffold_case(text, None, INIT_CLOCK)
                self.assertEqual("safety_support", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["safety"])
                self.assertTrue(MODULE.analyze_safety(text).immediate)

    def test_nonpersonal_payload_can_be_followed_by_a_live_personal_override(self) -> None:
        text = "请翻译：‘我要自杀。枪在房间里。’上面说的就是我现在的计划。"
        case = MODULE.scaffold_case(text, None, INIT_CLOCK)
        self.assertEqual("safety_support", case["route"]["mode"])
        self.assertTrue(MODULE.analyze_safety(text).immediate)

    def test_patient_quote_and_novel_proofreading_remain_nonpersonal(self) -> None:
        controls = (
            "这是一位患者的原话：‘我要自杀。枪在房间里。’请只校对。",
            "For a novel, proofread: I will kill myself tonight. The gun is beside me.",
        )
        for text in controls:
            with self.subTest(text=text):
                case = MODULE.scaffold_case(text, None, INIT_CLOCK)
                self.assertNotEqual("safety_support", case["route"]["mode"])
                self.assertFalse(case["risk_flags"]["safety"])


class GeneratedLanguageSemanticFuzz(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = json.loads(FIXTURE.read_text(encoding="utf-8"))
        errors = MODULE.validate_case(cls.base)
        if errors:
            raise AssertionError(errors)

    def codes(self, text: str, field: str) -> set[str]:
        case = copy.deepcopy(self.base)
        if field == "minimal_question":
            case["analysis"]["minimal_question"]["text"] = text
        elif field == "candidate_reason":
            case["analysis"]["candidate_variables"][0]["reason"] = text
        elif field == "experiment_action":
            case["analysis"]["experiment"]["action"] = text
        else:
            raise AssertionError(field)
        return {item["code"] for item in MODULE.validate_case(case)}

    def test_disclaimer_or_negation_cannot_mask_a_later_diagnosis_assertion(self) -> None:
        assertions = (
            "I cannot diagnose you but this clearly confirms ADHD.",
            "不能确诊只是这些表现足以证明你有 ADHD。",
            "You definitely have ADHD.",
        )
        for text in assertions:
            with self.subTest(text=text):
                self.assertIn(
                    "diagnosis_confirmation_generated",
                    self.codes(text, "minimal_question"),
                )

    def test_english_diagnosis_revocation_is_rejected(self) -> None:
        self.assertIn(
            "diagnosis_override_generated",
            self.codes("Your formal ADHD diagnosis was wrong.", "minimal_question"),
        )

    def test_bilingual_invented_motives_and_commitments_are_rejected(self) -> None:
        motives = (
            "我故意没回他，好让他受点教训。",
            "I ignored my partner to punish them.",
        )
        for text in motives:
            with self.subTest(text=text):
                self.assertIn(
                    "unreported_psychological_cause",
                    self.codes(text, "candidate_reason"),
                )
        commitments = (
            "I will reply every day at eight.",
            "从明天开始，我每晚给你发消息。",
        )
        for text in commitments:
            with self.subTest(text=text):
                self.assertIn(
                    "unreported_personal_claim",
                    self.codes(text, "experiment_action"),
                )


class StablePreferenceSemanticFuzz(unittest.TestCase):
    def test_reception_synonym_cannot_correct_large_gathering_preference(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v70-preference-") as temp:
            root = Path(temp)
            scaffold_path = root / "scaffold.json"
            analysis_path = root / "analysis.json"
            case_path = root / "case.json"
            scaffolded = run_cli(
                "scaffold",
                "--text",
                MIXED_PREFERENCE_TEXT,
                "--out",
                str(scaffold_path),
                "--case-id",
                "v70-preference",
                "--clock",
                INIT_CLOCK,
            )
            self.assertEqual(0, scaffolded.returncode, scaffolded.stdout + scaffolded.stderr)
            scaffold = json.loads(scaffold_path.read_text(encoding="utf-8"))
            analysis = copy.deepcopy(scaffold["analysis"])
            source = analysis["judgments"][1]["source"]
            judgment_id = f"J-{source['evidence_id']}-{source['start']}-{source['end']}"
            analysis["candidate_variables"] = [
                {
                    "name": "准备时间",
                    "status": "hypothesis",
                    "reason": "只检验公开表达，不改变工作或社交偏好",
                }
            ]
            analysis["experiment"] = {
                "status": "planned",
                "target_claim": "在有十五分钟准备时，我无法完成一次三分钟公开表达",
                "target_judgment_ids": [judgment_id],
                "primary_variable": "准备时间",
                "duration": {"value": 7, "unit": "days"},
                "action": "把三分钟团队更新安排在百人酒会上完成。",
                "kept_constant": ["表达主题", "录制时长"],
                "measures": ["是否完成三分钟录制"],
                "support_if": ["在固定准备时间后仍未完成三分钟录制"],
                "weaken_if": ["在固定准备时间后完成三分钟录制"],
                "reversible": True,
                "reversibility_note": "实验结束后不改变原工作与社交安排",
            }
            write_json(analysis_path, analysis)
            compiled = run_cli(
                "compile",
                "--scaffold",
                str(scaffold_path),
                "--analysis",
                str(analysis_path),
                "--out",
                str(case_path),
                "--clock",
                PLAN_CLOCK,
            )
            self.assertNotEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
            self.assertFalse(case_path.exists())
            self.assertIn(
                "preference_correction",
                {item["code"] for item in payload(compiled)["errors"]},
            )


if __name__ == "__main__":
    unittest.main()
