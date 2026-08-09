#!/usr/bin/env python3
"""V10 red contracts frozen from the independent V9 attribution audit."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
PREREGISTRATION = ROOT / "evals" / "raw" / "v2-forward" / "attribution-blind-v9" / "preregistration.json"
PREREGISTRATION_SHA256 = "5558771f08770ab32f19da2b2c384c837e137ca143930e5e42a09b4036132572"
CLOCK = "2026-08-06T22:00:00Z"


def scaffold(text: str, case_id: str) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "scaffold",
            "--text",
            text,
            "--case-id",
            case_id,
            "--clock",
            CLOCK,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


def frozen_cases() -> list[dict]:
    raw = PREREGISTRATION.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PREREGISTRATION_SHA256:
        raise AssertionError("V9 attribution preregistration hash changed")
    payload = json.loads(raw)
    return [side for pair in payload["pairs"] for side in (pair["positive"], pair["negative"])]


EXPECTED_SOURCE = {
    "personal_other_attribution": "other_person_attribution",
    "personal_self_label": "user_self_description",
    "personal_ai_inference": "ai_inference",
    "personal_clinical_only": "reported_clinical_diagnosis",
    "personal_formal_scale_only": "formal_scale_result",
    "personal_formal_scale_with_verdict": "formal_scale_result",
    "personal_social_label": "social_media_label",
    "personal_negated_clinical_plus_ai": "ai_inference",
    "personal_suspicion_not_diagnosis": "user_self_description",
}

DECONSTRUCT_CLASSES = {
    "mixed_personal_sources",
    "personal_ai_inference",
    "personal_formal_scale_with_verdict",
    "personal_negated_clinical_plus_ai",
    "personal_other_attribution",
    "personal_self_label",
    "personal_social_label",
    "personal_suspicion_not_diagnosis",
}

CLINICAL_VERDICT_PATTERN = re.compile(
    r"(?:所以|因此|于是)[^。；;\n]{0,72}(?:永远|注定|不可能|不能|无法|没法|不适合|没救)",
    re.IGNORECASE,
)

EVENT_ORACLE_CASES = {
    "A01-P",
    "A01-N",
    "B01-P",
    "B01-N",
    "B03-P",
    "B04-P",
    "B06-P",
    "B08-N",
    "B09-P",
    "C01-P",
    "C01-N",
    "C12-P",
    "C12-N",
    "D05-N",
    "E02-P",
    "E02-N",
}


class V10AttributionBlindRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = frozen_cases()
        if len(cls.cases) != 128:
            raise AssertionError(f"expected 128 frozen cases, found {len(cls.cases)}")

    def test_all_128_preregistered_actor_source_and_material_boundaries(self) -> None:
        for expected in self.cases:
            with self.subTest(case_id=expected["id"]):
                case = scaffold(expected["text"], expected["id"])
                labels = case["analysis"]["labels"]
                label_texts = [item["text"] for item in labels]
                sources = {item["source_type"] for item in labels}
                context_claims = case["analysis"].get("context_claims", [])
                claim_texts = [item["claim"] for item in context_claims]
                claim_sources = {item["source"] for item in context_claims}

                for term in expected.get("required_terms", []):
                    self.assertTrue(
                        any(
                            term.casefold() in value.casefold()
                            for value in label_texts + claim_texts
                        ),
                        f"missing required term {term!r}: labels={label_texts}, context={claim_texts}",
                    )
                for term in expected.get("forbidden_terms", []):
                    self.assertFalse(
                        any(term.casefold() in value.casefold() for value in label_texts),
                        f"forbidden term {term!r} became current-user evidence: {label_texts}",
                    )
                for source in expected.get("required_sources", []):
                    self.assertIn(source, sources | claim_sources)
                for source in expected.get("forbidden_sources", []):
                    self.assertNotIn(source, sources)

                expected_class = expected["expected_class"]
                if expected_class == "nonpersonal_material":
                    self.assertEqual([], labels)
                    self.assertNotEqual("deconstruct", case["route"]["mode"])
                    self.assertFalse(case["risk_flags"]["clinical"])
                elif expected_class in EXPECTED_SOURCE:
                    self.assertIn(
                        EXPECTED_SOURCE[expected_class],
                        sources | claim_sources,
                    )

                if expected_class in DECONSTRUCT_CLASSES:
                    self.assertEqual("deconstruct", case["route"]["mode"])
                elif expected_class == "personal_clinical_only":
                    expected_route = (
                        "deconstruct"
                        if CLINICAL_VERDICT_PATTERN.search(expected["text"])
                        else "clinical_report_only"
                    )
                    self.assertEqual(expected_route, case["route"]["mode"])

    def test_representative_accepted_labels_emit_explicit_attribution_events(self) -> None:
        expected_by_id = {item["id"]: item for item in self.cases}
        for case_id in sorted(EVENT_ORACLE_CASES):
            expected = expected_by_id[case_id]
            with self.subTest(case_id=case_id):
                case = scaffold(expected["text"], case_id)
                labels = case["analysis"]["labels"]
                if expected["expected_class"] == "nonpersonal_material":
                    self.assertEqual([], labels)
                    continue
                self.assertTrue(labels)
                for label in labels:
                    event = label.get("attribution")
                    self.assertIsInstance(event, dict)
                    self.assertEqual("current_user", event["target"]["role"])
                    self.assertEqual("personal", event["discourse_context"]["kind"])
                    self.assertEqual(label["source_type"], event["source"]["type"])
                    self.assertEqual(label["evidence_status"], event["source"]["evidence_status"])
                    self.assertEqual(label["source"]["start"], event["label"]["start"])
                    self.assertEqual(label["source"]["end"], event["label"]["end"])


if __name__ == "__main__":
    unittest.main()
