from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round82PackagedSemanticMatrixRedTests(unittest.TestCase):
    """The installed runtime must retain the latest semantic boundaries."""

    def test_runtime_self_test_binds_round77_through_round81_invariants(self) -> None:
        result = casefile.runtime_self_test()
        required = {
            "safety_high_confidence_family_matrix",
            "safety_resolved_lifecycle_matrix",
            "passthrough_finite_transform_ownership",
            "safety_event_local_polarity",
            "safety_clause_local_slot_binding",
        }
        self.assertLessEqual(required, set(result["checks"]))
        self.assertTrue(all(result["checks"][key] for key in required))
        self.assertTrue(result["valid"])


if __name__ == "__main__":
    unittest.main()
