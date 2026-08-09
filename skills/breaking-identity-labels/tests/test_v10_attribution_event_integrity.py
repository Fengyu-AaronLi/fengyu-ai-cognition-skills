#!/usr/bin/env python3
"""V10 event-integrity contracts: attribution data must replay from evidence."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
GOOD = ROOT / "tests" / "fixtures" / "valid-c01.json"
CLOCK = "2026-08-06T23:00:00Z"


def validation_codes(case: dict) -> set[str]:
    with tempfile.TemporaryDirectory(prefix="identity-attribution-integrity-") as tmp:
        path = Path(tmp) / "case.json"
        path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(CLI), "validate", str(path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    if result.returncode == 0:
        return set()
    payload = json.loads(result.stdout)
    return {item["code"] for item in payload["errors"]}


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


class V10AttributionEventIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.good = json.loads(GOOD.read_text(encoding="utf-8"))

    def mutated(self) -> tuple[dict, dict]:
        case = copy.deepcopy(self.good)
        event = case["analysis"]["labels"][0]["attribution"]
        return case, event

    def test_event_source_cannot_diverge_from_label_source(self) -> None:
        case, event = self.mutated()
        event["source"] = {
            "type": "ai_inference",
            "evidence_status": "unverified_inference",
        }
        self.assertIn("attribution_source_mismatch", validation_codes(case))

    def test_persisted_label_target_must_be_current_user(self) -> None:
        case, event = self.mutated()
        event["target"]["role"] = "third_party"
        self.assertIn("attribution_target_invalid", validation_codes(case))

    def test_persisted_label_must_come_from_personal_discourse(self) -> None:
        case, event = self.mutated()
        event["discourse_context"]["kind"] = "quoted_material"
        self.assertIn("attribution_discourse_invalid", validation_codes(case))

    def test_event_label_span_must_equal_cited_source_span(self) -> None:
        case, event = self.mutated()
        event["label"]["start"] += 1
        self.assertIn("attribution_label_span_mismatch", validation_codes(case))

    def test_component_text_must_replay_exact_evidence_span(self) -> None:
        case, event = self.mutated()
        event["speaker"]["text"] = "AI"
        self.assertIn("attribution_text_mismatch", validation_codes(case))

    def test_component_span_cannot_leave_evidence(self) -> None:
        case, event = self.mutated()
        event["predicate"]["span"]["end"] = len(case["evidence"][0]["text"]) + 1
        self.assertIn("attribution_span_invalid", validation_codes(case))

    def test_personal_words_inside_protected_material_do_not_override_its_context(self) -> None:
        inputs = (
            "这是一条标注样本：“我本人说我是控制狂，所以团队都会离开。”只判断因果词。",
            "JSON fixture 的字段值是“我本人说我是控制狂”，请检查解析器，不分析现实用户。",
            "论文原文是“记录的是我本人：我是固定型人格”，这里只校对引文。",
        )
        for text in inputs:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual([], case["analysis"]["labels"])
                self.assertFalse(case["route"]["trigger"])

    def test_predicate_subject_controls_source_instead_of_nearest_prior_actor(self) -> None:
        cases = (
            (
                "同事把短视频发给我，短视频说我是“潮痕型”。",
                "social_media_label",
                "短视频",
                "说我是",
            ),
            (
                "主管把AI生成的摘要转给我，并在评语里称我为“协作断点”。",
                "other_person_attribution",
                "主管",
                "称我为",
            ),
        )
        for text, source, speaker, predicate in cases:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual(1, len(case["analysis"]["labels"]))
                label = case["analysis"]["labels"][0]
                event = label["attribution"]
                self.assertEqual(source, label["source_type"])
                self.assertEqual(speaker, event["speaker"]["text"])
                self.assertEqual(predicate, event["predicate"]["text"])

    def test_social_predicate_is_not_overridden_by_later_self_attribution(self) -> None:
        case = scaffold("短视频说我是“潮痕型”，但我自己仍明确自称“低恢复型”。")
        sources = {item["text"]: item["source_type"] for item in case["analysis"]["labels"]}
        self.assertEqual("social_media_label", sources["潮痕型"])
        self.assertEqual("user_self_description", sources["低恢复型"])


if __name__ == "__main__":
    unittest.main()
