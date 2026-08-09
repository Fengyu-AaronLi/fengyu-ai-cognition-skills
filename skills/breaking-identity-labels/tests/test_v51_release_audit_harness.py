from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "run_release_audits.py"
EXPECTED_AUDITS = {
    "independent_attribution_audit",
    "independent_clinical_safety_audit",
    "independent_state_integrity_audit",
    "release_package_audit",
}


class ReleaseAuditHarnessTests(unittest.TestCase):
    def test_self_check_exposes_four_nonempty_shell_free_suites(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HARNESS), "self-check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(set(payload["audit_ids"]), EXPECTED_AUDITS)
        self.assertTrue(all(payload["command_counts"][key] > 0 for key in EXPECTED_AUDITS))

    def test_suite_definitions_reference_existing_scripts_and_use_argv_arrays(self) -> None:
        spec = importlib.util.spec_from_file_location("release_audits", HARNESS)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(set(module.AUDIT_SUITES), EXPECTED_AUDITS)
        for suite in module.AUDIT_SUITES.values():
            self.assertTrue(suite)
            for command in suite:
                self.assertIsInstance(command, tuple)
                self.assertGreaterEqual(len(command), 2)
                self.assertFalse(any(token in {"sh", "bash", "zsh", "-c"} for token in command))
                script = ROOT / command[0]
                self.assertTrue(script.is_file(), command)


if __name__ == "__main__":
    unittest.main()
