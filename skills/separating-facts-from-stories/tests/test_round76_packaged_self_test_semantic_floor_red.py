from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round76PackagedSelfTestSemanticFloorRedTests(unittest.TestCase):
    """The lean installed runtime must retain the newest semantic invariants."""

    def test_packaged_self_test_covers_event_scope_and_translation_ownership(self) -> None:
        result = casefile.runtime_self_test()
        required = {
            "safety_event_scoped_resolution",
            "safety_current_risk_polarity",
            "safety_translation_instruction_boundary",
            "safety_legal_event_scope",
        }
        self.assertTrue(result["valid"], result)
        self.assertTrue(required.issubset(result["checks"]), result["checks"])
        self.assertTrue(all(result["checks"][name] for name in required))


if __name__ == "__main__":
    unittest.main()
