#!/usr/bin/env python3
"""V62 contract: source validation does not reuse stale release proof."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ValidationReleaseSeparationTests(unittest.TestCase):
    def test_source_validation_does_not_project_release_eligibility(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "evals" / "validate.py")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("release gate not evaluated (source-only)", result.stdout)
        self.assertNotIn("release_eligible: true", result.stdout)
        self.assertNotIn("release gate current (candidate)", result.stdout)


if __name__ == "__main__":
    unittest.main()
