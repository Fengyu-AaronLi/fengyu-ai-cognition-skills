#!/usr/bin/env python3
"""R70 contract: source validation is reproducible without mutable release state."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "evals" / "validate.py"


def run_validator(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class SourceValidationDependencyContract(unittest.TestCase):
    def test_default_source_validation_does_not_require_mutable_release_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v70-missing-state-") as temp:
            missing = Path(temp) / "release-gate.json"
            result = run_validator("--release-state", str(missing))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("release gate not evaluated (source-only)", result.stdout)

    def test_release_state_check_is_explicit_and_fails_closed_when_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v70-missing-state-") as temp:
            missing = Path(temp) / "release-gate.json"
            result = run_validator(
                "--include-release-state",
                "--release-state",
                str(missing),
            )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("cannot read valid JSON from release state", result.stderr)


if __name__ == "__main__":
    unittest.main()
