from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = SKILL_DIR / "schemas" / "casefile.schema.json"
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round140VersionedLegacyEpochContractRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_new_contract_has_an_explicit_version_pair(self) -> None:
        self.assertEqual("3.2.0", casefile.SCHEMA_VERSION)
        self.assertEqual("4.4.0", casefile.SKILL_VERSION)
        self.assertEqual("4.4.0", casefile.VALIDATOR_VERSION)

    def test_schema_models_the_optional_legacy_epoch_exactly(self) -> None:
        properties = self.schema["properties"]
        self.assertIn("legacy_epoch", properties)
        self.assertNotIn("legacy_epoch", self.schema["required"])
        self.assertEqual(
            {"$ref": "#/$defs/legacy_epoch"}, properties["legacy_epoch"]
        )
        epoch = self.schema["$defs"]["legacy_epoch"]
        self.assertFalse(epoch["additionalProperties"])
        self.assertEqual(casefile.LEGACY_EPOCH_KEYS, set(epoch["required"]))
        self.assertEqual(casefile.LEGACY_EPOCH_KEYS, set(epoch["properties"]))

    def test_new_root_without_a_legacy_epoch_is_schema_valid(self) -> None:
        root = casefile.make_draft(
            "只翻译成英文：你好。", "round140-new-root", "passthrough"
        )
        self.assertEqual(
            set(root),
            casefile.ROOT_KEYS - {"legacy_epoch"},
        )
        self.assertEqual([], casefile.validate_casefile(root))

    def test_unattested_v411_root_cannot_self_authorize_migration(self) -> None:
        previous = casefile.make_draft(
            "只翻译成英文：你好。", "round140-v411-root", "passthrough"
        )
        previous["schema_version"] = "3.1.0"
        previous["skill_version"] = "4.1.1"
        codes = {
            item["code"]
            for item in casefile.validate_casefile(previous)
        }
        self.assertIn("VERSION_PAIR_UNSUPPORTED", codes)
        with self.assertRaisesRegex(ValueError, "unsupported previous version pair"):
            casefile.start_update(
                previous,
                "只翻译成英文：谢谢。",
            )

    def test_v411_is_not_claimed_as_a_migratable_pair(self) -> None:
        previous_pair = ("3.1.0", "4.1.1")
        self.assertNotIn(previous_pair, casefile.MIGRATABLE_VERSION_PAIRS)
        self.assertNotIn(previous_pair, casefile.VERSION_PROFILE_BY_PAIR)
        self.assertNotIn(previous_pair, casefile.VERSION_PAIR_RANK)
        self.assertNotIn((previous_pair, casefile.CURRENT_VERSION_PAIR), casefile.VERSION_MIGRATION_EDGES)


if __name__ == "__main__":
    unittest.main()
