from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
LONG_FIXTURE = (
    SKILL_DIR
    / "evals"
    / "raw"
    / "with-skill-v30-failed-attempts"
    / "round129-versioned-update-red-v401"
    / "long-narrative-exact-anchor"
    / "artifacts"
    / "separation.json"
)
LONG_RECEIPT = LONG_FIXTURE.parent.parent / "receipts" / "validation.json"
CORPUS = SKILL_DIR / "evals" / "legacy-migration-corpus.json"
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


def _assert_fixture_bound(testcase: unittest.TestCase) -> None:
    entries = json.loads(CORPUS.read_text(encoding="utf-8"))["entries"]
    relative = LONG_FIXTURE.relative_to(SKILL_DIR).as_posix()
    entry = next(item for item in entries if item["artifact"] == relative)
    testcase.assertEqual(
        entry["artifact_sha256"],
        hashlib.sha256(LONG_FIXTURE.read_bytes()).hexdigest(),
    )
    testcase.assertEqual(
        entry["receipt_sha256"],
        hashlib.sha256(LONG_RECEIPT.read_bytes()).hexdigest(),
    )
    testcase.assertEqual(
        entry["casefile_sha256"],
        casefile.canonical_sha256(
            json.loads(LONG_FIXTURE.read_text(encoding="utf-8"))
        ),
    )


class Round139LegacyEpochRenderingRedTests(unittest.TestCase):
    def setUp(self) -> None:
        _assert_fixture_bound(self)
        self.previous = json.loads(LONG_FIXTURE.read_text(encoding="utf-8"))
        self.receipt = json.loads(LONG_RECEIPT.read_text(encoding="utf-8"))
        self.current = casefile.start_update(
            self.previous,
            "我看到门口多了一把钥匙。",
            legacy_receipt=self.receipt,
        )

    def test_migration_records_the_exact_legacy_boundary(self) -> None:
        epoch = self.current["legacy_epoch"]
        self.assertEqual(self.previous["revision"], epoch["through_revision"])
        self.assertEqual(
            {
                "schema_version": self.previous["schema_version"],
                "skill_version": self.previous["skill_version"],
            },
            epoch["source_version_pair"],
        )
        for field, id_field in (
            ("inputs", "input_ids"),
            ("source_spans", "source_span_ids"),
            ("claims", "claim_ids"),
            ("evidence", "evidence_ids"),
        ):
            self.assertEqual(
                [item["id"] for item in self.previous[field]],
                epoch[id_field],
            )

    def test_missing_or_mutated_epoch_boundary_fails(self) -> None:
        missing = copy.deepcopy(self.current)
        missing.pop("legacy_epoch")
        missing_codes = {
            item["code"]
            for item in casefile.validate_casefile(
                missing,
                previous=self.previous,
                legacy_receipt=self.receipt,
            )
        }
        self.assertIn("LEGACY_EPOCH_REQUIRED", missing_codes)

        mutated = copy.deepcopy(self.current)
        mutated["legacy_epoch"]["claim_ids"] = []
        mutated_codes = {
            item["code"]
            for item in casefile.validate_casefile(
                mutated,
                previous=self.previous,
                legacy_receipt=self.receipt,
            )
        }
        self.assertIn("LEGACY_EPOCH_MISMATCH", mutated_codes)

    def test_renderer_discloses_legacy_source_semantics(self) -> None:
        rendered = casefile.render_markdown(self.current)
        self.assertIn("历史版本保留", rendered)
        self.assertIn("当前版本未重新认定来源类型", rendered)

    def test_epoch_boundary_is_immutable_in_later_revisions(self) -> None:
        second = casefile.start_update(
            self.current,
            "我看到桌上多了一张便签。",
        )
        self.assertEqual(
            [], casefile.validate_casefile(second, previous=self.current)
        )
        self.assertEqual(self.current["legacy_epoch"], second["legacy_epoch"])
        tampered = copy.deepcopy(second)
        tampered["legacy_epoch"]["through_revision"] += 1
        codes = {
            item["code"]
            for item in casefile.validate_casefile(tampered, previous=self.current)
        }
        self.assertIn("LEGACY_EPOCH_MUTATED", codes)


if __name__ == "__main__":
    unittest.main()
