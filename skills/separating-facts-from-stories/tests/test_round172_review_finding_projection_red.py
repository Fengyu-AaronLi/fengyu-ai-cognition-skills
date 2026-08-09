#!/usr/bin/env python3
"""Round 172 RED: loop findings are projections of host review findings."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import improvement_loop  # noqa: E402
import test_round86_workflow_step_ledger_red as round86  # noqa: E402


class Round172ReviewFindingProjectionRedTests(unittest.TestCase):
    def test_phase_cannot_rewrite_summary_after_host_review(self) -> None:
        graph = round86.Round86WorkflowStepLedgerRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round172-red-") as temp_dir:
            paths, state = graph.make_graph_candidate(Path(temp_dir))
            preflight, _ = graph.write_receipt(paths, state, "preflight_snapshot")
            state = graph.record(paths, "preflight_snapshot", preflight)
            accepted = state["iterations"][-1]["step_ledger"][-1]["receipt"]["sha256"]
            receipt_path, _ = graph.write_receipt(
                paths,
                state,
                "adversarial_review",
                dependency_receipts={"preflight_snapshot": accepted},
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["finding_events"] = [
                {
                    "action": "open",
                    "finding_id": "R172-BOUND-FINDING",
                    "severity": "P1",
                    "summary": "Original host-observed summary.",
                    "reproducer": "Run the frozen reproducer.",
                    "actual": "The invalid transition succeeds.",
                    "expected": "The invalid transition is rejected.",
                }
            ]
            graph.sync_phase_payload(paths, receipt)
            receipt["finding_events"][0]["summary"] = (
                "Phase producer rewrote the host finding."
            )
            receipt_path.write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(improvement_loop.LoopError) as raised:
                graph.record(paths, "adversarial_review", receipt_path)
            self.assertEqual("PHASE_PAYLOAD_INVALID", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
