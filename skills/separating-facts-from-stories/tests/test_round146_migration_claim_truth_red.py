from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
CORPUS_PATH = SKILL_DIR / "evals" / "legacy-migration-corpus.json"
SCHEMA_PATH = SKILL_DIR / "schemas" / "casefile.schema.json"
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


def _attested_pairs() -> set[tuple[str, str]]:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    pairs: set[tuple[str, str]] = set()
    for entry in corpus["entries"]:
        artifact = json.loads(
            (SKILL_DIR / entry["artifact"]).read_text(encoding="utf-8")
        )
        pairs.add((artifact["schema_version"], artifact["skill_version"]))
    return pairs


def _schema_legacy_pairs() -> set[tuple[str, str]]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    variants = schema["$defs"]["legacy_version_pair"]["oneOf"]
    return {
        (
            item["properties"]["schema_version"]["const"],
            item["properties"]["skill_version"]["const"],
        )
        for item in variants
    }


class Round146MigrationClaimTruthRedTests(unittest.TestCase):
    def test_migratable_claim_equals_the_attested_corpus_pairs(self) -> None:
        attested = _attested_pairs()
        self.assertEqual(
            {("3.0.0", "4.0.0"), ("3.0.0", "4.0.1")},
            attested,
        )
        self.assertEqual(attested, casefile.MIGRATABLE_VERSION_PAIRS)

    def test_runtime_and_schema_expose_only_attested_legacy_pairs(self) -> None:
        expected = _attested_pairs()
        self.assertEqual(
            expected | {casefile.CURRENT_VERSION_PAIR},
            casefile.SUPPORTED_VERSION_PAIRS,
        )
        self.assertEqual(expected, _schema_legacy_pairs())
        self.assertEqual(
            expected | {casefile.CURRENT_VERSION_PAIR},
            set(casefile.VERSION_PROFILE_BY_PAIR),
        )
        self.assertEqual(
            expected | {casefile.CURRENT_VERSION_PAIR},
            set(casefile.VERSION_PAIR_RANK),
        )

    def test_unattested_local_candidate_versions_are_explicitly_unsupported(self) -> None:
        for pair in (
            ("3.0.0", "4.0.2"),
            ("3.1.0", "4.1.0"),
            ("3.1.0", "4.1.1"),
            ("3.2.0", "4.2.0"),
        ):
            with self.subTest(pair=pair):
                draft = casefile.make_draft(
                    "只翻译成英文：你好。",
                    "round146-unattested-version",
                    "passthrough",
                )
                draft["schema_version"], draft["skill_version"] = pair
                codes = {
                    item["code"] for item in casefile.validate_casefile(draft)
                }
                self.assertIn("VERSION_PAIR_UNSUPPORTED", codes)


if __name__ == "__main__":
    unittest.main()
