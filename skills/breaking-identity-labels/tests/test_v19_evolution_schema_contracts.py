#!/usr/bin/env python3
"""V19 red contracts for evolution state, receipt and release schema parity."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


class EvolutionSchemaContractTests(unittest.TestCase):
    def test_release_gate_requires_workflow_and_governance_bindings(self) -> None:
        schema = read_schema("release-gate.schema.json")
        required = set(schema["required"])
        self.assertIn("workflow_path", required)
        self.assertIn("governance_files", required)
        artifact = schema["$defs"]["artifactHashes"]
        artifact_required = set(artifact["required"])
        self.assertIn("governance_tree_sha256", artifact_required)
        self.assertIn("workflow_sha256", artifact_required)

    def test_run_state_schema_describes_resumable_projection_and_lineage(self) -> None:
        schema = read_schema("evolution-run-state.schema.json")
        required = set(schema["required"])
        self.assertTrue(
            {
                "run_id",
                "candidate_id",
                "workflow_id",
                "workflow_path",
                "workflow_sha256",
                "status",
                "current_step",
                "steps",
                "event_count",
                "event_head_sha256",
                "distribution_status",
                "publication_actions_performed",
            }.issubset(required)
        )
        properties = schema["properties"]
        self.assertEqual("local_unpublished", properties["distribution_status"]["const"])
        self.assertFalse(properties["publication_actions_performed"]["const"])
        self.assertIn("predecessor_run_id", properties)
        self.assertIn("carry_over_blockers", properties)
        step = schema["$defs"]["stepProjection"]
        self.assertEqual(
            {"pending", "waiting", "completed", "failed"},
            set(step["properties"]["status"]["enum"]),
        )

    def test_command_receipt_schema_binds_raw_output_and_assertion(self) -> None:
        schema = read_schema("evolution-command-receipt.schema.json")
        required = set(schema["required"])
        self.assertTrue(
            {
                "run_id",
                "candidate_id",
                "workflow_sha256",
                "step_id",
                "argv",
                "exit_code",
                "assertion",
                "assertion_passed",
                "stdout_path",
                "stdout_sha256",
                "stderr_path",
                "stderr_sha256",
            }.issubset(required)
        )
        self.assertEqual(
            {"red", "exit_zero"},
            set(schema["properties"]["assertion"]["enum"]),
        )


if __name__ == "__main__":
    unittest.main()
