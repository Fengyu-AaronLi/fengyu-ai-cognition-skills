#!/usr/bin/env python3
"""V72 red contracts for terminal audits and genuine evolution succession.

These tests use only temporary repositories.  They exercise the public
controller CLI and never read or write the real release-gate state.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from test_v13_architecture_integrity_regressions import (
    AuditFixture,
    json_payload,
    sha256,
    write_json,
)
from test_v14_evolution_lineage_and_governance import (
    V14Fixture,
    digest,
)


AUDIT_ID = "independent_attribution_audit"


class TerminalAuditFixture:
    """Create current-schema audit receipts for one frozen temp candidate."""

    def __init__(self, root: Path) -> None:
        self.fixture = AuditFixture(root)
        self.fixture.freeze()
        self.script = root / "audits" / "attribution.py"
        self.input_file = root / "inputs" / "attribution-cases.json"
        self.script.parent.mkdir(parents=True, exist_ok=True)
        self.input_file.parent.mkdir(parents=True, exist_ok=True)
        self.script.write_text("print('audit pass')\n", encoding="utf-8")
        self.input_file.write_text('{"cases":["V72"]}\n', encoding="utf-8")

    def receipt(self, name: str, blockers: list[dict[str, str]]) -> str:
        relative = self.fixture.receipt(AUDIT_ID, name=name)
        path = self.fixture.root / relative
        receipt = json.loads(path.read_text(encoding="utf-8"))
        evidence_dir = self.fixture.root / "evals" / "receipts" / name
        preregistration = {
            "schema_version": "1.0",
            "audit_id": AUDIT_ID,
            "candidate_id": receipt["candidate"]["candidate_id"],
            "completed_run_sha256": receipt["completed_run"]["run_state_sha256"],
            "objective": "Attempt to falsify the frozen V72 candidate.",
            "commands": [
                {
                    "argv": ["audits/attribution.py"],
                    "input_files": [
                        "audits/attribution.py",
                        "inputs/attribution-cases.json",
                    ],
                }
            ],
            "pass_condition": "The preregistered audit exits zero and reports no blocker.",
            "live_model_called": False,
        }
        preregistration_path = evidence_dir / "preregistration.json"
        write_json(preregistration_path, preregistration)
        receipt["schema_version"] = "1.2"
        receipt["preregistration"]["case_set_sha256"] = sha256(
            preregistration_path.read_bytes()
        )
        receipt["commands"][0].update(
            {
                "argv": [sys.executable, str(self.script.resolve())],
                "script_path": "audits/attribution.py",
                "script_sha256": sha256(self.script.read_bytes()),
                "input_snapshot": {
                    "cwd": ".",
                    "environment": {"PYTHONHASHSEED": "0"},
                    "files": [
                        {
                            "path": "audits/attribution.py",
                            "sha256": sha256(self.script.read_bytes()),
                        },
                        {
                            "path": "inputs/attribution-cases.json",
                            "sha256": sha256(self.input_file.read_bytes()),
                        },
                    ],
                },
            }
        )
        receipt["blockers"] = blockers
        receipt["status"] = "blocked" if blockers else "passed"
        write_json(path, receipt)
        return relative

    def record(self, relative: str):
        return self.fixture.run(
            "record-audit",
            "--audit-id",
            AUDIT_ID,
            "--receipt",
            relative,
        )


class AuditResultTerminalityTests(unittest.TestCase):
    def test_blocked_audit_cannot_be_replaced_by_later_pass_for_same_candidate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v72-audit-terminal-") as temp:
            fixture = TerminalAuditFixture(Path(temp))
            blocked = fixture.receipt(
                "v72-blocked",
                [{"id": "B-V72-AUDIT", "severity": "P0"}],
            )
            first = fixture.record(blocked)
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            passing = fixture.receipt("v72-later-pass", [])
            state_before = fixture.fixture.state_path.read_bytes()

            second = fixture.record(passing)

            self.assertEqual(3, second.returncode, second.stdout + second.stderr)
            self.assertIn(
                "audit_result_terminal",
                set(json_payload(second).get("errors", [])),
            )
            self.assertEqual(state_before, fixture.fixture.state_path.read_bytes())
            state = json.loads(state_before)
            audit = next(item for item in state["audits"] if item["audit_id"] == AUDIT_ID)
            self.assertEqual("blocked", audit["status"])
            self.assertEqual(1, state["blocker_count"])
            self.assertEqual("blocked", state["decision"])


class TerminalPredecessorLineageTests(unittest.TestCase):
    def test_failed_terminal_run_can_seed_a_successor_lineage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v72-failed-lineage-") as temp:
            fixture = V14Fixture(Path(temp))
            previous = fixture.root / "evals" / "runs" / "v72-failed"
            started = fixture.start(
                fixture.failed_workflow,
                previous,
                "v72-failed",
                "candidate-v72-failed",
            )
            self.assertEqual(2, started.returncode, started.stdout + started.stderr)
            previous_state = json.loads(
                (previous / "run-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual("failed", previous_state["status"])
            state_bytes = (previous / "run-state.json").read_bytes()
            event_bytes = (previous / "events.jsonl").read_bytes()
            receipt_bytes = (previous / "receipts" / "green.json").read_bytes()
            target = fixture.root / "evals" / "runs" / "v72-successor"

            advanced = fixture.controller(
                "next-iteration",
                "--previous-run-dir",
                str(previous),
                "--run-dir",
                str(target),
                "--run-id",
                "v72-successor",
                "--candidate-id",
                "candidate-v72-successor",
            )

            self.assertEqual(2, advanced.returncode, advanced.stdout + advanced.stderr)
            self.assertTrue(target.is_dir())
            successor = json.loads(
                (target / "run-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual("v72-failed", successor["predecessor_run_id"])
            self.assertEqual(
                "candidate-v72-failed", successor["predecessor_candidate_id"]
            )
            binding = successor["predecessor_binding"]
            self.assertEqual(digest(previous / "run-state.json"), binding["run_state_sha256"])
            self.assertEqual(previous_state["event_head_sha256"], binding["event_head_sha256"])
            self.assertRegex(binding["receipt_tree_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(state_bytes, (previous / "run-state.json").read_bytes())
            self.assertEqual(event_bytes, (previous / "events.jsonl").read_bytes())
            self.assertEqual(receipt_bytes, (previous / "receipts" / "green.json").read_bytes())

    def test_successor_uses_new_workflow_after_live_runtime_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v72-historical-snapshot-") as temp:
            fixture = V14Fixture(Path(temp))
            previous = fixture.root / "evals" / "runs" / "v72-complete"
            started = fixture.start(
                fixture.workflow,
                previous,
                "v72-complete",
                "candidate-v72-complete",
            )
            self.assertEqual(0, started.returncode, started.stdout + started.stderr)
            previous_state = json.loads(
                (previous / "run-state.json").read_text(encoding="utf-8")
            )
            state_bytes = (previous / "run-state.json").read_bytes()
            event_bytes = (previous / "events.jsonl").read_bytes()
            receipt_bytes = (previous / "receipts" / "green.json").read_bytes()

            runtime = fixture.root / "scripts" / "identity_label_case.py"
            runtime.write_text("print('runtime v72 successor')\n", encoding="utf-8")
            successor_worker = fixture.root / "scripts" / "worker_successor.py"
            successor_worker.write_text("print('successor OK')\n", encoding="utf-8")
            successor_workflow = fixture.root / "workflows" / "v72-successor.json"
            write_json(
                successor_workflow,
                {
                    "schema_version": "1.0",
                    "workflow_id": "identity-v72-successor",
                    "description": "Successor workflow intentionally differs from its predecessor.",
                    "steps": [
                        {
                            "id": "successor_green",
                            "kind": "command",
                            "depends_on": [],
                            "argv": [
                                "{python}",
                                "{root}/scripts/worker_successor.py",
                            ],
                            "expected": "exit_zero",
                        }
                    ],
                },
            )
            target = fixture.root / "evals" / "runs" / "v72-next-workflow"

            advanced = fixture.controller(
                "next-iteration",
                "--previous-run-dir",
                str(previous),
                "--workflow",
                str(successor_workflow),
                "--run-dir",
                str(target),
                "--run-id",
                "v72-next-workflow",
                "--candidate-id",
                "candidate-v72-next-workflow",
            )

            self.assertEqual(0, advanced.returncode, advanced.stdout + advanced.stderr)
            successor = json.loads(
                (target / "run-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual("complete", successor["status"])
            self.assertEqual(
                "workflows/v72-successor.json", successor["workflow_path"]
            )
            self.assertEqual(digest(successor_workflow), successor["workflow_sha256"])
            self.assertEqual("v72-complete", successor["predecessor_run_id"])
            self.assertEqual(
                digest(previous / "run-state.json"),
                successor["predecessor_binding"]["run_state_sha256"],
            )
            self.assertEqual(
                previous_state["completed_artifacts"],
                successor["predecessor_binding"]["completed_artifacts"],
            )
            self.assertEqual(state_bytes, (previous / "run-state.json").read_bytes())
            self.assertEqual(event_bytes, (previous / "events.jsonl").read_bytes())
            self.assertEqual(receipt_bytes, (previous / "receipts" / "green.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
