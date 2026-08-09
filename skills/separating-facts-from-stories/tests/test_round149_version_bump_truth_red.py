from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round149VersionBumpTruthRedTests(unittest.TestCase):
    def test_current_behavior_identity_is_4_4_0(self) -> None:
        self.assertEqual("4.4.0", casefile.SKILL_VERSION)
        self.assertEqual("4.4.0", casefile.VALIDATOR_VERSION)
        self.assertEqual(("3.2.0", "4.4.0"), casefile.CURRENT_VERSION_PAIR)
        schema = json.loads(
            (SKILL_DIR / "schemas" / "casefile.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("4.4.0", schema["properties"]["skill_version"]["const"])

    def test_unattested_4_3_0_artifact_is_not_silently_migratable(self) -> None:
        draft = casefile.make_draft(
            "他看了消息六个小时没回。", "round149-version", "standard"
        )
        draft["skill_version"] = "4.3.0"
        codes = {item["code"] for item in casefile.validate_casefile(draft)}
        self.assertIn("VERSION_PAIR_UNSUPPORTED", codes)


if __name__ == "__main__":
    unittest.main()
