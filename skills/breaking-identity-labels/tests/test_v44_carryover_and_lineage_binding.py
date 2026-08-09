#!/usr/bin/env python3
"""V44 contracts: blockers and predecessor evidence survive every iteration."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from test_v14_evolution_lineage_and_governance import V14Fixture, result_payload


class CarryoverAndLineageBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v44-lineage-")
        self.fixture = V14Fixture(Path(self.temporary.name))
        self.r1 = self.fixture.root / "evals" / "runs" / "v44-r1"
        started = self.fixture.start(
            self.fixture.workflow,
            self.r1,
            "v44-r1",
            "candidate-v44-r1",
        )
        if started.returncode != 0:
            raise AssertionError(started.stdout + started.stderr)
        self.r2 = self.fixture.root / "evals" / "runs" / "v44-r2"
        advanced = self.fixture.controller(
            "next-iteration",
            "--previous-run-dir",
            str(self.r1),
            "--run-dir",
            str(self.r2),
            "--run-id",
            "v44-r2",
            "--candidate-id",
            "candidate-v44-r2",
            "--carry-over-blocker",
            "B-V44:P0:evals/findings/v14.md",
        )
        if advanced.returncode != 0:
            raise AssertionError(advanced.stdout + advanced.stderr)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_carryover_evidence_is_hashed_and_continuously_revalidated(self) -> None:
        state = json.loads((self.r2 / "run-state.json").read_text(encoding="utf-8"))
        binding = state["carry_over_blocker_bindings"][0]
        self.assertEqual("B-V44", binding["id"])
        self.assertEqual("open", binding["status"])
        self.assertRegex(binding["evidence_sha256"], r"^[0-9a-f]{64}$")

        evidence = self.fixture.root / "evals" / "findings" / "v14.md"
        evidence.write_text("changed after carry-over\n", encoding="utf-8")
        status = self.fixture.controller("status", "--run-dir", str(self.r2))

        self.assertEqual(3, status.returncode, status.stdout + status.stderr)
        self.assertIn(
            "evolution_carry_over_evidence_hash_mismatch",
            set(result_payload(status).get("errors", [])),
        )

    def test_freeze_automatically_inherits_open_carryover_blocker(self) -> None:
        frozen = self.fixture.controller(
            "freeze",
            "--candidate-id",
            "candidate-v44-r2",
            "--workflow",
            str(self.fixture.workflow),
            "--completed-run-dir",
            str(self.r2),
        )
        self.assertEqual(0, frozen.returncode, frozen.stdout + frozen.stderr)
        state = json.loads(self.fixture.release_state.read_text(encoding="utf-8"))
        self.assertEqual("blocked", state["decision"])
        self.assertEqual(1, state["blocker_count"])
        self.assertEqual("B-V44", state["blockers"][0]["id"])
        self.assertRegex(state["blockers"][0]["evidence_sha256"], r"^[0-9a-f]{64}$")

    def test_next_iteration_cannot_silently_drop_an_open_blocker(self) -> None:
        r3 = self.fixture.root / "evals" / "runs" / "v44-r3"
        advanced = self.fixture.controller(
            "next-iteration",
            "--previous-run-dir",
            str(self.r2),
            "--run-dir",
            str(r3),
            "--run-id",
            "v44-r3",
            "--candidate-id",
            "candidate-v44-r3",
        )
        self.assertEqual(0, advanced.returncode, advanced.stdout + advanced.stderr)
        state = json.loads((r3 / "run-state.json").read_text(encoding="utf-8"))
        self.assertEqual(["B-V44"], [item["id"] for item in state["carry_over_blockers"]])
        self.assertEqual(["B-V44"], [item["id"] for item in state["carry_over_blocker_bindings"]])

    def test_successor_status_revalidates_bound_predecessor_files(self) -> None:
        state = json.loads((self.r2 / "run-state.json").read_text(encoding="utf-8"))
        binding = state["predecessor_binding"]
        self.assertEqual("v44-r1", binding["run_id"])
        self.assertRegex(binding["run_state_sha256"], r"^[0-9a-f]{64}$")

        predecessor_state = self.r1 / "run-state.json"
        predecessor_state.write_text(
            predecessor_state.read_text(encoding="utf-8") + " ",
            encoding="utf-8",
        )
        status = self.fixture.controller("status", "--run-dir", str(self.r2))

        self.assertEqual(3, status.returncode, status.stdout + status.stderr)
        self.assertIn(
            "evolution_predecessor_state_hash_mismatch",
            set(result_payload(status).get("errors", [])),
        )


if __name__ == "__main__":
    unittest.main()
