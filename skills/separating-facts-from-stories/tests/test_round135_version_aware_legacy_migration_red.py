from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[1]
FIXTURE_DIR = (
    SKILL_DIR
    / "evals"
    / "raw"
    / "with-skill-v30-pre-round124-stale"
    / "self-identity-story"
)
FIXTURE_PATH = FIXTURE_DIR / "artifacts" / "separation.json"
RECEIPT_PATH = FIXTURE_DIR / "receipts" / "validation.json"
CORPUS_PATH = SKILL_DIR / "evals" / "legacy-migration-corpus.json"
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_fixture_bound(
    testcase: unittest.TestCase, artifact: Path, receipt: Path
) -> None:
    entries = _load(CORPUS_PATH)["entries"]
    relative = artifact.relative_to(SKILL_DIR).as_posix()
    entry = next(item for item in entries if item["artifact"] == relative)
    testcase.assertEqual(
        entry["artifact_sha256"], hashlib.sha256(artifact.read_bytes()).hexdigest()
    )
    testcase.assertEqual(
        entry["receipt_sha256"], hashlib.sha256(receipt.read_bytes()).hexdigest()
    )
    testcase.assertEqual(
        entry["casefile_sha256"], casefile.canonical_sha256(_load(artifact))
    )


class Round135VersionAwareLegacyMigrationRedTests(unittest.TestCase):
    def setUp(self) -> None:
        _assert_fixture_bound(self, FIXTURE_PATH, RECEIPT_PATH)
        self.previous = _load(FIXTURE_PATH)
        self.receipt = _load(RECEIPT_PATH)

    def test_frozen_real_v400_fixture_and_receipt_are_bound(self) -> None:
        receipt = _load(RECEIPT_PATH)
        self.assertEqual(("3.0.0", "4.0.0"), casefile._casefile_version_pair(self.previous))
        self.assertTrue(receipt["valid"])
        self.assertEqual("4.0.0", receipt["validator_version"])
        self.assertEqual(
            receipt["artifact_sha256"],
            hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            [],
            casefile.validate_casefile(
                self.previous, legacy_receipt=self.receipt
            ),
        )

    def test_migration_preserves_legacy_prefix_and_validates_current_suffix(self) -> None:
        current = casefile.start_update(
            self.previous,
            "我看到门口多了一把钥匙。",
            legacy_receipt=self.receipt,
        )
        self.assertEqual(casefile.CURRENT_VERSION_PAIR, casefile._casefile_version_pair(current))
        self.assertEqual(2, current["revision"])
        self.assertEqual(
            casefile.canonical_sha256(self.previous),
            current["previous_case_sha256"],
        )
        for field in (
            "inputs",
            "source_spans",
            "claims",
            "evidence",
            "evidence_links",
            "unknowns",
            "hypotheses",
        ):
            prior = self.previous[field]
            self.assertEqual(prior, current[field][: len(prior)])
        self.assertEqual("SP5", current["source_spans"][4]["id"])
        self.assertEqual(
            [],
            casefile.validate_casefile(
                current,
                previous=self.previous,
                legacy_receipt=self.receipt,
            ),
        )

    def test_current_parser_never_reprocesses_legacy_i1(self) -> None:
        current = casefile.start_update(
            self.previous,
            "我看到门口多了一把钥匙。",
            legacy_receipt=self.receipt,
        )
        original = casefile.generate_source_spans
        seen: list[str] = []

        def guarded(input_id: str, text: str, start_index: int = 1):
            seen.append(input_id)
            if input_id == "I1":
                raise AssertionError("current parser reprocessed legacy I1")
            return original(input_id, text, start_index)

        with mock.patch.object(casefile, "generate_source_spans", side_effect=guarded):
            self.assertEqual(
                [],
                casefile.validate_casefile(
                    current,
                    previous=self.previous,
                    legacy_receipt=self.receipt,
                ),
            )
        self.assertEqual(["I2"], seen)

    def test_legacy_span_tampering_is_not_hidden_by_profile(self) -> None:
        tampered = copy.deepcopy(self.previous)
        tampered["source_spans"][0]["text"] = "两周没有完成计划"
        tampered["source_spans"][0]["sha256"] = casefile.sha256_text(
            tampered["source_spans"][0]["text"]
        )
        codes = {
            item["code"]
            for item in casefile.validate_casefile(
                tampered, legacy_receipt=self.receipt
            )
        }
        self.assertIn("SOURCE_SPAN_TEXT_MISMATCH", codes)

    def test_current_suffix_tampering_fails_closed(self) -> None:
        current = casefile.start_update(
            self.previous,
            "我看到门口多了一把钥匙。",
            legacy_receipt=self.receipt,
        )
        current["source_spans"][-1]["start"] += 1
        codes = {
            item["code"]
            for item in casefile.validate_casefile(
                current,
                previous=self.previous,
                legacy_receipt=self.receipt,
            )
        }
        self.assertIn("CURRENT_SOURCE_SPAN_SET_MISMATCH", codes)


if __name__ == "__main__":
    unittest.main()
