from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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


class Round144TrustedLegacyAttestationRedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.trusted_artifact = _load(FIXTURE_PATH)
        self.trusted_receipt = _load(RECEIPT_PATH)

    def test_self_forged_receipt_cannot_attest_a_new_legacy_artifact(self) -> None:
        forged = _standard_shell(
            "[非原话] 老板说：‘手机送修，刚拿回来’。"
        )
        _append_attributed_statement(forged, _full_quote_span(forged))
        forged["schema_version"] = "3.0.0"
        forged["skill_version"] = "4.0.1"
        forged_receipt = {
            "valid": True,
            "error_count": 0,
            "errors": [],
            "casefile_sha256": casefile.canonical_sha256(forged),
            "schema_version": "3.0.0",
            "validator_version": "4.0.1",
        }
        codes = {
            item["code"]
            for item in casefile.validate_casefile(
                forged,
                legacy_receipt=forged_receipt,
            )
        }
        self.assertIn("LEGACY_ARTIFACT_NOT_ATTESTED", codes)

    def test_receipt_must_match_the_attested_receipt_fingerprint(self) -> None:
        altered_receipt = copy.deepcopy(self.trusted_receipt)
        altered_receipt["untrusted_extension"] = True
        codes = {
            item["code"]
            for item in casefile.validate_casefile(
                self.trusted_artifact,
                legacy_receipt=altered_receipt,
            )
        }
        self.assertIn("LEGACY_RECEIPT_NOT_ATTESTED", codes)

    def test_missing_trust_registry_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round144-") as temp_dir:
            missing = Path(temp_dir) / "missing-corpus.json"
            with mock.patch.object(
                casefile,
                "TRUSTED_LEGACY_CORPUS_PATH",
                missing,
                create=True,
            ):
                codes = {
                    item["code"]
                    for item in casefile.validate_casefile(
                        self.trusted_artifact,
                        legacy_receipt=self.trusted_receipt,
                    )
                }
        self.assertIn("LEGACY_TRUST_REGISTRY_UNAVAILABLE", codes)

    def test_exact_attested_artifact_and_receipt_remain_accepted(self) -> None:
        self.assertEqual(
            [],
            casefile.validate_casefile(
                self.trusted_artifact,
                legacy_receipt=self.trusted_receipt,
            ),
        )


if __name__ == "__main__":
    unittest.main()
