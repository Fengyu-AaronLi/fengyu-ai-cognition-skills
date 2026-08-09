from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
FIXTURE = (
    SKILL_DIR
    / "evals"
    / "raw"
    / "with-skill-v30-pre-round124-stale"
    / "self-identity-story"
    / "artifacts"
    / "separation.json"
)
RECEIPT = FIXTURE.parent.parent / "receipts" / "validation.json"
CORPUS = SKILL_DIR / "evals" / "legacy-migration-corpus.json"
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


def _assert_fixture_bound(testcase: unittest.TestCase) -> None:
    entries = json.loads(CORPUS.read_text(encoding="utf-8"))["entries"]
    relative = FIXTURE.relative_to(SKILL_DIR).as_posix()
    entry = next(item for item in entries if item["artifact"] == relative)
    testcase.assertEqual(
        entry["artifact_sha256"], hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    )
    testcase.assertEqual(
        entry["receipt_sha256"], hashlib.sha256(RECEIPT.read_bytes()).hexdigest()
    )
    testcase.assertEqual(
        entry["casefile_sha256"],
        casefile.canonical_sha256(json.loads(FIXTURE.read_text(encoding="utf-8"))),
    )


class Round138LegacyProfileFailClosedRedTests(unittest.TestCase):
    def setUp(self) -> None:
        _assert_fixture_bound(self)
        self.previous = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))

    def test_legacy_version_cannot_relabel_a_story_as_fact(self) -> None:
        tampered = copy.deepcopy(self.previous)
        claim = tampered["claims"][1]
        claim["kind"] = "observable_fact"
        claim["observation_type"] = "task_or_action_event"
        claim["source_type"] = "user_direct_observation"
        claim["epistemic_status"] = "reported"
        claim["diagnostic_boundary"] = False
        codes = {
            item["code"]
            for item in casefile.validate_casefile(
                tampered, legacy_receipt=self.receipt
            )
        }
        self.assertIn("LEGACY_FACT_STORY_LEAK", codes)

    def test_legacy_anchor_mutation_still_fails(self) -> None:
        tampered = copy.deepcopy(self.previous)
        tampered["claims"][0]["source_span_id"] = "SP3"
        codes = {
            item["code"]
            for item in casefile.validate_casefile(
                tampered, legacy_receipt=self.receipt
            )
        }
        self.assertTrue(
            {"SOURCE_SPAN_MISMATCH", "CLAIM_TEXT_NOT_ANCHOR"} & codes,
            codes,
        )

    def test_missing_current_profile_fails_closed(self) -> None:
        current = casefile.make_draft("他六小时没回。", "round138-profile", "standard")
        profiles = dict(casefile.VERSION_PROFILE_BY_PAIR)
        profiles.pop(casefile.CURRENT_VERSION_PAIR)
        with mock.patch.dict(casefile.VERSION_PROFILE_BY_PAIR, profiles, clear=True):
            codes = {item["code"] for item in casefile.validate_casefile(current)}
        self.assertIn("VERSION_PROFILE_UNAVAILABLE", codes)

    def test_unregistered_forward_edge_fails_closed(self) -> None:
        current = casefile.start_update(
            self.previous,
            "我看到门口多了一把钥匙。",
            legacy_receipt=self.receipt,
        )
        edges = set(casefile.VERSION_MIGRATION_EDGES)
        edges.remove(
            (
                casefile._casefile_version_pair(self.previous),
                casefile.CURRENT_VERSION_PAIR,
            )
        )
        with mock.patch.object(casefile, "VERSION_MIGRATION_EDGES", edges):
            codes = {
                item["code"]
                for item in casefile.validate_casefile(
                    current,
                    previous=self.previous,
                    legacy_receipt=self.receipt,
                )
            }
        self.assertIn("VERSION_MIGRATION_EDGE_UNSUPPORTED", codes)

    def test_start_update_rejects_an_unsupported_previous_pair(self) -> None:
        unsupported = copy.deepcopy(self.previous)
        unsupported["skill_version"] = "9.9.9"
        with self.assertRaisesRegex(ValueError, "unsupported previous version pair"):
            casefile.start_update(
                unsupported,
                "我看到门口多了一把钥匙。",
            )


if __name__ == "__main__":
    unittest.main()
