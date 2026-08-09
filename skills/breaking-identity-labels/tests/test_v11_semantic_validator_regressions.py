#!/usr/bin/env python3
"""V11 validator contracts: replayable fields must also match parsed meaning."""

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
CLOCK = "2026-08-06T23:45:00Z"
TEXT = "姐姐对我说我是控制狂，所以我不适合做产品经理。"


def scaffold() -> dict:
    result = subprocess.run(
        [sys.executable, str(CLI), "scaffold", "--text", TEXT, "--clock", CLOCK],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


def validation_codes(case: dict) -> set[str]:
    with tempfile.TemporaryDirectory(prefix="identity-v11-semantic-validator-") as tmp:
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


class V11SemanticValidatorRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.good = scaffold()

    def mutation(self) -> tuple[dict, dict]:
        case = copy.deepcopy(self.good)
        return case, case["analysis"]["labels"][0]["attribution"]

    def test_rejects_replayable_but_wrong_speaker(self) -> None:
        case, event = self.mutation()
        event["speaker"] = {
            "role": "other_person",
            "text": "我",
            "span": {"start": 3, "end": 4},
        }
        self.assertIn("attribution_speaker_semantic_mismatch", validation_codes(case))

    def test_rejects_recipient_substituted_for_proposition_target(self) -> None:
        case, event = self.mutation()
        event["target"] = {
            "role": "current_user",
            "text": "我",
            "resolution": "explicit",
            "span": {"start": 3, "end": 4},
        }
        self.assertIn("attribution_target_semantic_mismatch", validation_codes(case))

    def test_rejects_forged_predicate_polarity(self) -> None:
        case, event = self.mutation()
        event["predicate"]["polarity"] = "negated"
        self.assertIn("attribution_predicate_semantic_mismatch", validation_codes(case))

    def test_rejects_narrowed_personal_discourse_span(self) -> None:
        case, event = self.mutation()
        event["discourse_context"]["span"] = copy.deepcopy(event["label"])
        self.assertIn("attribution_discourse_semantic_mismatch", validation_codes(case))


if __name__ == "__main__":
    unittest.main()
