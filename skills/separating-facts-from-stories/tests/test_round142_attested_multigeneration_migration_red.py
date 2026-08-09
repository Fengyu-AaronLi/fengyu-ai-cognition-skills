from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
FIXTURE_DIR = (
    SKILL_DIR
    / "evals"
    / "raw"
    / "with-skill-v30-failed-attempts"
    / "round129-versioned-update-red-v401"
    / "long-narrative-exact-anchor"
)
FIXTURE_PATH = FIXTURE_DIR / "artifacts" / "separation.json"
RECEIPT_PATH = FIXTURE_DIR / "receipts" / "validation.json"
CORPUS_PATH = SKILL_DIR / "evals" / "legacy-migration-corpus.json"
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
from test_round134_attribution_scope_variants_red import (  # noqa: E402
    _append_attributed_statement,
    _full_quote_span,
    _standard_shell,
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_fixture_bound(testcase: unittest.TestCase) -> None:
    entries = _load(CORPUS_PATH)["entries"]
    relative = FIXTURE_PATH.relative_to(SKILL_DIR).as_posix()
    entry = next(item for item in entries if item["artifact"] == relative)
    testcase.assertEqual(
        entry["artifact_sha256"],
        hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest(),
    )
    testcase.assertEqual(
        entry["receipt_sha256"],
        hashlib.sha256(RECEIPT_PATH.read_bytes()).hexdigest(),
    )
    testcase.assertEqual(
        entry["casefile_sha256"], casefile.canonical_sha256(_load(FIXTURE_PATH))
    )


class Round142AttestedMultigenerationMigrationRedTests(unittest.TestCase):
    def setUp(self) -> None:
        _assert_fixture_bound(self)
        self.legacy = _load(FIXTURE_PATH)
        self.receipt = _load(RECEIPT_PATH)

    def test_legacy_root_requires_an_external_hash_bound_receipt(self) -> None:
        codes = {item["code"] for item in casefile.validate_casefile(self.legacy)}
        self.assertIn("LEGACY_RECEIPT_REQUIRED", codes)
        self.assertEqual(
            [],
            casefile.validate_casefile(
                self.legacy,
                legacy_receipt=self.receipt,
            ),
        )

        tampered_receipt = copy.deepcopy(self.receipt)
        tampered_receipt["casefile_sha256"] = "0" * 64
        tampered_codes = {
            item["code"]
            for item in casefile.validate_casefile(
                self.legacy,
                legacy_receipt=tampered_receipt,
            )
        }
        self.assertIn("LEGACY_RECEIPT_HASH_MISMATCH", tampered_codes)

    def test_start_update_rejects_silent_legacy_migration(self) -> None:
        with self.assertRaisesRegex(ValueError, "LEGACY_RECEIPT_REQUIRED"):
            casefile.start_update(self.legacy, "我看到门口多了一把钥匙。")

    def test_attested_legacy_history_survives_multiple_current_updates(self) -> None:
        revision_two = casefile.start_update(
            self.legacy,
            "我看到门口多了一把钥匙。",
            legacy_receipt=self.receipt,
        )
        self.assertEqual(
            [],
            casefile.validate_casefile(
                revision_two,
                previous=self.legacy,
                legacy_receipt=self.receipt,
            ),
        )

        revision_three = casefile.start_update(
            revision_two,
            "我看到桌上多了一张便签。",
        )
        self.assertEqual(
            revision_two["legacy_epoch"], revision_three["legacy_epoch"]
        )
        self.assertEqual(
            [],
            casefile.validate_casefile(revision_three, previous=revision_two),
        )

    def test_current_only_history_cannot_inject_a_legacy_epoch(self) -> None:
        revision_one = casefile.make_draft(
            "只翻译成英文：你好。", "round142-current-root", "passthrough"
        )
        revision_two = casefile.start_update(
            revision_one, "只翻译成英文：谢谢。"
        )
        revision_two["legacy_epoch"] = {
            "through_revision": 1,
            "source_version_pair": {
                "schema_version": "3.0.0",
                "skill_version": "4.0.1",
            },
            "input_ids": [item["id"] for item in revision_two["inputs"]],
            "source_span_ids": [
                item["id"] for item in revision_two["source_spans"]
            ],
            "claim_ids": [],
            "evidence_ids": [],
        }
        codes = {
            item["code"]
            for item in casefile.validate_casefile(
                revision_two, previous=revision_one
            )
        }
        self.assertIn("LEGACY_EPOCH_UNEXPECTED", codes)

    def test_version_strings_alone_cannot_launder_an_invalid_root(self) -> None:
        forged = _standard_shell(
            "[非原话] 老板说：‘手机送修，刚拿回来’。"
        )
        _append_attributed_statement(forged, _full_quote_span(forged))
        current_codes = {
            item["code"] for item in casefile.validate_casefile(forged)
        }
        self.assertIn("DIRECT_QUOTE_NOT_ASSERTED", current_codes)

        forged["schema_version"] = "3.0.0"
        forged["skill_version"] = "4.0.1"
        legacy_codes = {
            item["code"] for item in casefile.validate_casefile(forged)
        }
        self.assertIn("LEGACY_RECEIPT_REQUIRED", legacy_codes)

        mismatched_codes = {
            item["code"]
            for item in casefile.validate_casefile(
                forged,
                legacy_receipt=self.receipt,
            )
        }
        self.assertIn("LEGACY_RECEIPT_HASH_MISMATCH", mismatched_codes)

    def test_renderer_never_calls_legacy_items_current(self) -> None:
        current = casefile.start_update(
            self.legacy,
            "我看到门口多了一把钥匙。",
            legacy_receipt=self.receipt,
        )
        rendered = casefile.render_markdown(current)
        self.assertNotIn("[当前意愿、决定或边界]", rendered)
        self.assertIn("[历史版本保留的意愿、决定或边界分类]", rendered)
        self.assertNotIn("保留为当前报告中的记录", rendered)
        self.assertIn("保留为历史版本记录", rendered)

    def test_new_validation_receipt_names_artifact_pair_and_profile(self) -> None:
        receipt = casefile.validation_receipt(FIXTURE_PATH, self.legacy, [])
        self.assertEqual(
            {"schema_version": "3.0.0", "skill_version": "4.0.1"},
            receipt["artifact_version_pair"],
        )
        self.assertEqual("legacy-v401", receipt["validation_profile"])
        self.assertEqual(casefile.VALIDATOR_VERSION, receipt["validator_version"])


if __name__ == "__main__":
    unittest.main()
