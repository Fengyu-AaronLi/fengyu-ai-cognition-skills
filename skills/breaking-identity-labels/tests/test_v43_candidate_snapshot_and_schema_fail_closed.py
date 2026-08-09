#!/usr/bin/env python3
"""V43 contracts: completed bytes stay bound and schemas fail closed."""

from __future__ import annotations

import json
import runpy
import tempfile
import unittest
from pathlib import Path

from test_v37_release_completed_run_binding import ReleaseRunFixture, payload, write_json


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts" / "run_evolution.py"


class CandidateSnapshotAndSchemaFailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v43-binding-")
        self.fixture = ReleaseRunFixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_candidate_change_after_completed_run_blocks_status_and_freeze(self) -> None:
        self.fixture.complete_run(candidate_id="candidate-v43")
        runtime = self.fixture.root / "scripts" / "identity_label_case.py"
        runtime.write_text("print('changed after completion')\n", encoding="utf-8")

        status = self.fixture.controller("status", "--run-dir", str(self.fixture.run_dir))
        frozen = self.fixture.freeze(candidate_id="candidate-v43")

        self.assertEqual(3, status.returncode, status.stdout + status.stderr)
        self.assertEqual(3, frozen.returncode, frozen.stdout + frozen.stderr)
        self.assertIn("evolution_candidate_snapshot_mismatch", set(payload(status).get("errors", [])))
        self.assertIn("evolution_candidate_snapshot_mismatch", set(payload(frozen).get("errors", [])))
        self.assertFalse(self.fixture.release_state.exists())

    def test_freeze_binds_exact_completed_artifacts_not_only_candidate_name(self) -> None:
        self.fixture.complete_run(candidate_id="candidate-v43")
        frozen = self.fixture.freeze(candidate_id="candidate-v43")
        self.assertEqual(0, frozen.returncode, frozen.stdout + frozen.stderr)

        state = json.loads(self.fixture.release_state.read_text(encoding="utf-8"))
        run_state = json.loads(
            (self.fixture.run_dir / "run-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(state["artifacts"], run_state["completed_artifacts"])
        self.assertEqual(
            state["artifacts"],
            state["completed_run"]["completed_artifacts"],
        )

    def test_boolean_const_is_not_satisfied_by_numeric_zero(self) -> None:
        self.fixture.complete_run(candidate_id="candidate-v43")
        path = self.fixture.run_dir / "run-state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["publication_actions_performed"] = 0
        write_json(path, state)

        result = self.fixture.controller("status", "--run-dir", str(self.fixture.run_dir))

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("evolution_run_state_schema_invalid", set(payload(result).get("errors", [])))

    def test_unknown_schema_assertion_keyword_fails_closed(self) -> None:
        module = runpy.run_path(str(CONTROLLER))
        module["_SCHEMA_CACHE"]["v43-unknown.schema.json"] = {
            "type": "object",
            "unknownAssertion": True,
        }

        errors = module["schema_validation_errors"]({}, "v43-unknown.schema.json")

        self.assertTrue(
            any("schema_keyword_unknown" in item for item in errors),
            errors,
        )

    def test_invalid_schema_keyword_value_fails_closed(self) -> None:
        module = runpy.run_path(str(CONTROLLER))
        module["_SCHEMA_CACHE"]["v43-invalid-value.schema.json"] = {
            "type": "array",
            "minItems": "one",
        }

        errors = module["schema_validation_errors"]([], "v43-invalid-value.schema.json")

        self.assertTrue(
            any("schema_keyword_value_invalid" in item for item in errors),
            errors,
        )

    def test_date_only_value_is_not_a_date_time(self) -> None:
        module = runpy.run_path(str(CONTROLLER))
        module["_SCHEMA_CACHE"]["v43-date-time.schema.json"] = {
            "type": "string",
            "format": "date-time",
        }

        errors = module["schema_validation_errors"](
            "2026-08-06",
            "v43-date-time.schema.json",
        )

        self.assertIn("$:date-time", errors)

    def test_json_numeric_equivalence_applies_to_unique_items_not_booleans(self) -> None:
        module = runpy.run_path(str(CONTROLLER))
        module["_SCHEMA_CACHE"]["v43-unique.schema.json"] = {
            "type": "array",
            "uniqueItems": True,
        }
        validator = module["schema_validation_errors"]

        self.assertIn("$:uniqueItems", validator([1, 1.0], "v43-unique.schema.json"))
        self.assertNotIn("$:uniqueItems", validator([False, 0], "v43-unique.schema.json"))

    def test_malformed_artifacts_returns_machine_readable_invalid_run(self) -> None:
        self.fixture.complete_run(candidate_id="candidate-v43")
        self.assertEqual(0, self.fixture.freeze(candidate_id="candidate-v43").returncode)
        state = json.loads(self.fixture.release_state.read_text(encoding="utf-8"))
        state["artifacts"] = None
        write_json(self.fixture.release_state, state)

        result = self.fixture.controller("check", "--allow-blocked")

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        result_payload = payload(result)
        self.assertFalse(result_payload.get("valid", True))
        self.assertIn("release_gate_schema_invalid", set(result_payload.get("errors", [])))
        self.assertIn("candidate_artifacts_not_object", set(result_payload.get("errors", [])))


if __name__ == "__main__":
    unittest.main()
