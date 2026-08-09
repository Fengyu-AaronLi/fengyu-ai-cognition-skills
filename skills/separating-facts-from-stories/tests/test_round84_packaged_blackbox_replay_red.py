from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round84PackagedBlackboxReplayRedTests(unittest.TestCase):
    """Installed self-test must retain the Round83 black-box invariants."""

    def test_runtime_self_test_binds_entrypoint_and_roleplay_scope(self) -> None:
        result = casefile.runtime_self_test()
        checks = result["checks"]
        for key in (
            "auto_entrypoint_passthrough_alignment",
            "safety_roleplay_scope_matrix",
        ):
            with self.subTest(key=key):
                self.assertIn(key, checks)
                self.assertIs(checks[key], True)


if __name__ == "__main__":
    unittest.main()
