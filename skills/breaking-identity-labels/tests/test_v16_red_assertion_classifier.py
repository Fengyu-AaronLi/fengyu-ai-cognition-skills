#!/usr/bin/env python3
"""V16 red contracts for distinguishing expected unittest failures from crashes."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts" / "run_evolution.py"
SPEC = importlib.util.spec_from_file_location("identity_evolution_controller", CONTROLLER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load evolution controller")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RedAssertionClassifierTests(unittest.TestCase):
    def test_unittest_assertion_failure_traceback_is_an_expected_red(self) -> None:
        stderr = """test_contract (__main__.ContractTests.test_contract) ... FAIL

======================================================================
FAIL: test_contract (__main__.ContractTests.test_contract)
----------------------------------------------------------------------
Traceback (most recent call last):
  File \"test_contract.py\", line 10, in test_contract
    self.assertEqual(3, 0)
AssertionError: 3 != 0

----------------------------------------------------------------------
Ran 1 test in 0.001s

FAILED (failures=1)
"""
        self.assertTrue(MODULE.assertion_for_command("red", 1, "", stderr))

    def test_runtime_error_is_not_misclassified_as_an_expected_red(self) -> None:
        stderr = """Traceback (most recent call last):
  File \"worker.py\", line 1, in <module>
    raise RuntimeError("boom")
RuntimeError: boom
"""
        self.assertFalse(MODULE.assertion_for_command("red", 1, "", stderr))

    def test_unittest_error_is_not_misclassified_as_an_expected_red(self) -> None:
        stderr = """Ran 1 test in 0.001s

FAILED (errors=1)
"""
        self.assertFalse(MODULE.assertion_for_command("red", 1, "", stderr))

    def test_zero_exit_is_never_an_expected_red(self) -> None:
        self.assertFalse(
            MODULE.assertion_for_command(
                "red",
                0,
                "Ran 1 test in 0.001s\nFAILED (failures=1)\n",
                "",
            )
        )


if __name__ == "__main__":
    unittest.main()
