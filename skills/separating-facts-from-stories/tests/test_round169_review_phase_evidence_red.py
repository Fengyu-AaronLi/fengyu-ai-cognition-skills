#!/usr/bin/env python3
"""Round 169 RED: graph review phases must carry real host attestations."""

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


class Round169ReviewPhaseEvidenceRedTests(unittest.TestCase):
    def test_self_declared_review_ids_and_hashes_cannot_advance_graph(self) -> None:
        graph = round86.Round86WorkflowStepLedgerRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round169-red-") as temp_dir:
            paths, state = graph.make_graph_candidate(Path(temp_dir))
            preflight, _ = graph.write_receipt(paths, state, "preflight_snapshot")
            state = graph.record(paths, "preflight_snapshot", preflight)
            receipt, artifact = graph.write_receipt(
                paths,
                state,
                "adversarial_review",
                dependency_receipts={
                    "preflight_snapshot": state["iterations"][-1]["step_ledger"][-1][
                        "receipt"
                    ]["sha256"]
                },
            )
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            payload["result"] = {
                "reviewer_ids": ["claimed-a", "claimed-b"],
                "execution_ids": ["claimed-run-a", "claimed-run-b"],
                "raw_artifact_sha256s": ["1" * 64, "2" * 64],
                "finding_ids": [],
                "trust_boundary": improvement_loop.REVIEW_TRUST_BOUNDARY,
            }
            artifact.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
            receipt_payload["artifacts"][0]["sha256"] = round86.sha256(artifact)
            receipt.write_text(
                json.dumps(receipt_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(improvement_loop.LoopError) as raised:
                graph.record(paths, "adversarial_review", receipt)
            self.assertEqual("PHASE_PAYLOAD_INVALID", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
