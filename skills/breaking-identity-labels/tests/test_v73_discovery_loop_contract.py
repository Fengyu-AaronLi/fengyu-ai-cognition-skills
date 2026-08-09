#!/usr/bin/env python3
"""R73 red contracts for executable, novel blind-spot discovery in the loop."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflows" / "v68-final-release.json"
DISCOVERY = ROOT / "scripts" / "run_blindspot_discovery.py"
REPORT_SCHEMA = ROOT / "evals" / "schemas" / "blindspot-discovery-report.schema.json"
TEST_MANIFEST = ROOT / "evals" / "test-generation-manifest.json"
REQUIRED_STRATEGIES = {
    "lexical_variant",
    "scope_collision",
    "nonpersonal_control",
}
REQUIRED_BINDINGS = {
    "skill": "SKILL.md",
    "runtime": "scripts/identity_label_case.py",
    "test_manifest": "evals/test-generation-manifest.json",
    "policy_rules": "references/policy-rules.md",
}


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DiscoveryWorkflowRedTests(unittest.TestCase):
    def test_release_workflow_executes_discovery_before_the_closed_world_regression(self) -> None:
        workflow = read_json(WORKFLOW)
        steps = {item["id"]: item for item in workflow["steps"]}
        self.assertTrue(
            "blindspot_discovery" in steps,
            "release workflow has no executable blindspot_discovery node",
        )
        if "blindspot_discovery" not in steps:
            return

        step = steps["blindspot_discovery"]
        argv = step.get("argv", [])
        inputs = set(step.get("input_files", []))
        self.assertEqual(step.get("kind"), "command")
        self.assertEqual(step.get("expected"), "exit_zero")
        self.assertIn("{root}/scripts/run_blindspot_discovery.py", argv)
        self.assertIn("--output", argv)
        self.assertIn("{run_dir}/blindspot-discovery.json", argv)
        self.assertIn("--seed", argv)
        self.assertTrue(
            {
                "scripts/run_blindspot_discovery.py",
                "evals/schemas/blindspot-discovery-report.schema.json",
                "SKILL.md",
                "scripts/identity_label_case.py",
                "evals/test-generation-manifest.json",
                "references/policy-rules.md",
            }.issubset(inputs)
        )
        self.assertIn("blindspot_discovery", steps["full_regression"].get("depends_on", []))

    def test_discovery_is_an_executable_generator_not_another_fixed_test_list(self) -> None:
        self.assertTrue(DISCOVERY.is_file(), "missing executable discovery runner")
        self.assertTrue(REPORT_SCHEMA.is_file(), "missing discovery report schema")
        if not DISCOVERY.is_file() or not REPORT_SCHEMA.is_file():
            return

        with tempfile.TemporaryDirectory(prefix="v73-blindspot-discovery-") as temporary:
            first = Path(temporary) / "first.json"
            second = Path(temporary) / "second.json"
            command = [
                sys.executable,
                str(DISCOVERY),
                "--root",
                str(ROOT),
                "--seed",
                "breaking-identity-labels-r73",
                "--minimum-probes",
                "6",
            ]
            run_one = subprocess.run(
                [*command, "--output", str(first)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            run_two = subprocess.run(
                [*command, "--output", str(second)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(run_one.returncode, 0, run_one.stderr or run_one.stdout)
            self.assertEqual(run_two.returncode, 0, run_two.stderr or run_two.stdout)
            if run_one.returncode != 0 or run_two.returncode != 0:
                return

            first_payload = read_json(first)
            second_payload = read_json(second)
            self.assertEqual(first_payload, second_payload)
            self.assertEqual(first_payload.get("schema_version"), "1.0")
            self.assertEqual(first_payload.get("run_type"), "deterministic_blindspot_discovery")
            self.assertEqual(first_payload.get("seed"), "breaking-identity-labels-r73")

            bindings = first_payload.get("candidate_bindings")
            self.assertIsInstance(bindings, dict)
            if isinstance(bindings, dict):
                self.assertEqual(set(bindings), set(REQUIRED_BINDINGS))
                for name, relative in REQUIRED_BINDINGS.items():
                    self.assertEqual(bindings[name].get("path"), relative)
                    self.assertEqual(bindings[name].get("sha256"), sha256(ROOT / relative))

            strategies = first_payload.get("strategy_inventory")
            self.assertIsInstance(strategies, list)
            if isinstance(strategies, list):
                self.assertTrue(REQUIRED_STRATEGIES.issubset(set(strategies)))

            probes = first_payload.get("probes")
            self.assertIsInstance(probes, list)
            if not isinstance(probes, list):
                return
            self.assertGreaterEqual(len(probes), 6)
            self.assertEqual(len({item.get("probe_id") for item in probes}), len(probes))
            self.assertTrue(REQUIRED_STRATEGIES.issubset({item.get("strategy") for item in probes}))
            for probe in probes:
                self.assertIsInstance(probe.get("input"), str)
                self.assertTrue(probe["input"].strip())
                self.assertIn(probe.get("status"), {"pass", "blindspot"})
                self.assertIsInstance(probe.get("expected_signals"), list)
                self.assertIsInstance(probe.get("observed_signals"), list)

            registered = read_json(TEST_MANIFEST)
            registered_corpus = "\n".join(
                (ROOT / item["path"]).read_text(encoding="utf-8")
                for item in registered["files"]
            )
            repeated = [probe["probe_id"] for probe in probes if probe["input"] in registered_corpus]
            self.assertEqual(
                repeated,
                [],
                "discovery cannot relabel exact registered test inputs as novel probes",
            )

            summary = first_payload.get("summary")
            self.assertIsInstance(summary, dict)
            if isinstance(summary, dict):
                self.assertEqual(summary.get("probe_count"), len(probes))
                self.assertEqual(
                    summary.get("blindspot_count"),
                    sum(item.get("status") == "blindspot" for item in probes),
                )


if __name__ == "__main__":
    unittest.main()
