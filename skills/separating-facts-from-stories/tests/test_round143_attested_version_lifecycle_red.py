from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = SKILL_DIR / "schemas" / "casefile.schema.json"
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


V420_PAIR = ("3.2.0", "4.2.0")


def _historical_receipt(data: dict) -> dict:
    return {
        "valid": True,
        "error_count": 0,
        "errors": [],
        "casefile_sha256": casefile.canonical_sha256(data),
        "schema_version": V420_PAIR[0],
        "validator_version": V420_PAIR[1],
    }


class Round143AttestedVersionLifecycleRedTests(unittest.TestCase):
    def test_security_boundary_has_a_new_current_version(self) -> None:
        self.assertEqual("3.2.0", casefile.SCHEMA_VERSION)
        self.assertEqual("4.4.0", casefile.SKILL_VERSION)
        self.assertEqual("4.4.0", casefile.VALIDATOR_VERSION)
        self.assertEqual(("3.2.0", "4.4.0"), casefile.CURRENT_VERSION_PAIR)

    def test_schema_is_bound_to_the_new_current_version(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual("3.2.0", schema["properties"]["schema_version"]["const"])
        self.assertEqual("4.4.0", schema["properties"]["skill_version"]["const"])

    def test_v420_is_not_claimed_as_a_migratable_profile(self) -> None:
        self.assertNotIn(V420_PAIR, casefile.MIGRATABLE_VERSION_PAIRS)
        self.assertNotIn(V420_PAIR, casefile.VERSION_PROFILE_BY_PAIR)
        self.assertNotIn(V420_PAIR, casefile.VERSION_PAIR_RANK)
        self.assertNotIn((V420_PAIR, casefile.CURRENT_VERSION_PAIR), casefile.VERSION_MIGRATION_EDGES)
        self.assertNotIn(
            (casefile.CURRENT_VERSION_PAIR, V420_PAIR),
            casefile.VERSION_MIGRATION_EDGES,
        )

    def test_v420_root_cannot_self_authorize_with_a_forged_receipt(self) -> None:
        previous = casefile.make_draft(
            "只翻译成英文：你好。", "round143-v420-root", "passthrough"
        )
        previous["schema_version"], previous["skill_version"] = V420_PAIR
        receipt = _historical_receipt(previous)

        unauthenticated_codes = {
            item["code"] for item in casefile.validate_casefile(previous)
        }
        self.assertIn("VERSION_PAIR_UNSUPPORTED", unauthenticated_codes)
        authenticated_codes = {
            item["code"]
            for item in casefile.validate_casefile(
                previous, legacy_receipt=receipt
            )
        }
        self.assertIn("VERSION_PAIR_UNSUPPORTED", authenticated_codes)
        with self.assertRaisesRegex(ValueError, "unsupported previous version pair"):
            casefile.start_update(
                previous,
                "只翻译成英文：谢谢。",
                legacy_receipt=receipt,
            )


if __name__ == "__main__":
    unittest.main()
