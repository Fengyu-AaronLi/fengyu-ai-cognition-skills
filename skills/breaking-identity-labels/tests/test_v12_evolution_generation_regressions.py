#!/usr/bin/env python3
"""V12 red contracts for an evolution loop that discovers future test generations."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_v11_evolution_controller import CONTROLLER, EvolutionFixture, write_json


ROOT = Path(__file__).resolve().parents[1]


class V12EvolutionGenerationRegressions(unittest.TestCase):
    def run_controller(
        self, fixture: EvolutionFixture, *args: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CONTROLLER),
                *args,
                "--root",
                str(fixture.root),
                "--state",
                str(fixture.state_path),
                "--test-manifest",
                str(fixture.manifest_path),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_sync_discovers_a_new_generation_and_adds_its_rule(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v12-generation-") as temp:
            fixture = EvolutionFixture(Path(temp))
            (fixture.root / "tests" / "test_v12_new_boundary.py").write_text(
                "# next generation\n", encoding="utf-8"
            )

            result = self.run_controller(fixture, "sync-tests")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            manifest = json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
            records = {item["path"]: item["generation"] for item in manifest["files"]}
            self.assertEqual("v12", records["tests/test_v12_new_boundary.py"])
            rules = {item["generation"]: item["pattern"] for item in manifest["generation_rules"]}
            self.assertEqual("tests/test_v12_*.py", rules["v12"])
            self.assertIn("v10", rules)
            self.assertIn("v11", rules)

    def test_check_rejects_a_generation_that_has_no_discovery_rule(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v12-missing-rule-") as temp:
            fixture = EvolutionFixture(Path(temp))
            (fixture.root / "tests" / "test_v12_new_boundary.py").write_text(
                "# next generation\n", encoding="utf-8"
            )
            synced = self.run_controller(fixture, "sync-tests")
            self.assertEqual(0, synced.returncode, synced.stdout + synced.stderr)

            manifest = json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
            manifest["generation_rules"] = [
                item for item in manifest["generation_rules"] if item["generation"] != "v12"
            ]
            write_json(fixture.manifest_path, manifest)
            fixture.write_state(passed=False)

            checked = self.run_controller(fixture, "check", "--allow-blocked")
            self.assertEqual(3, checked.returncode, checked.stdout + checked.stderr)
            self.assertIn(
                "test_manifest_generation_rule_missing:v12",
                json.loads(checked.stdout)["errors"],
            )


if __name__ == "__main__":
    unittest.main()
