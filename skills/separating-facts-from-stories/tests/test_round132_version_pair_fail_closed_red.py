from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round132VersionPairFailClosedRedTests(unittest.TestCase):
    """Malformed version metadata must be rejected, never crash validation."""

    def _draft(self) -> dict[str, Any]:
        return casefile.make_draft(
            "只翻译成英文：你好。", "round132-version-pair", "passthrough"
        )

    def test_unhashable_version_values_are_structurally_rejected(self) -> None:
        for field, value in (
            ("schema_version", []),
            ("schema_version", {}),
            ("skill_version", []),
            ("skill_version", {}),
        ):
            with self.subTest(field=field, value=value):
                draft = self._draft()
                draft[field] = value
                errors = casefile.validate_casefile(draft)
                self.assertIn(
                    "VERSION_PAIR_UNSUPPORTED",
                    {item["code"] for item in errors},
                )

    def test_cross_pair_rejection_does_not_mutate_the_artifact(self) -> None:
        draft = self._draft()
        draft["schema_version"] = "3.0.0"
        draft["skill_version"] = "4.1.1"
        before = copy.deepcopy(draft)
        errors = casefile.validate_casefile(draft)
        self.assertIn(
            "VERSION_PAIR_UNSUPPORTED", {item["code"] for item in errors}
        )
        self.assertEqual(before, draft)


if __name__ == "__main__":
    unittest.main()
