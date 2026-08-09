#!/usr/bin/env python3
"""Round 173 RED: STOP uses the review pair accepted by independent recheck."""

from __future__ import annotations

import argparse
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
from host_execution_fixture import write_host_review  # noqa: E402


class Round173StopReviewLineageRedTests(unittest.TestCase):
    def test_prove_stop_rejects_a_substituted_review_pair(self) -> None:
        graph = round86.Round86WorkflowStepLedgerRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round173-red-") as temp_dir:
            paths, state = graph.make_graph_candidate(Path(temp_dir))
            for step_id in improvement_loop.EXTERNAL_EXECUTION_STEPS:
                accepted = {
                    entry["step_id"]: entry["receipt"]["sha256"]
                    for entry in state["iterations"][-1]["step_ledger"]
                }
                dependencies = dict(improvement_loop.REQUIRED_EXECUTION_GRAPH)[step_id]
                receipt, _ = graph.write_receipt(
                    paths,
                    state,
                    step_id,
                    dependency_receipts={item: accepted[item] for item in dependencies},
                )
                state = graph.record(paths, step_id, receipt)
            source_sha = state["source_snapshot"]["sha256"]
            replacement_p0, _ = write_host_review(
                paths["repo"],
                "p0_zero",
                source_sha,
                suffix="round173-replacement-p0",
            )
            replacement_p1, _ = write_host_review(
                paths["repo"],
                "reproducible_p1_zero",
                source_sha,
                suffix="round173-replacement-p1",
            )
            eval_root = paths["repo"] / "eval-root"
            eval_root.mkdir()
            with self.assertRaises(improvement_loop.LoopError) as raised:
                improvement_loop.command_prove_stop(
                    argparse.Namespace(
                        state_dir=str(paths["state_dir"]),
                        eval_root=eval_root.relative_to(paths["repo"]).as_posix(),
                        p0_review=replacement_p0.relative_to(
                            paths["repo"].resolve()
                        ).as_posix(),
                        p1_review=replacement_p1.relative_to(
                            paths["repo"].resolve()
                        ).as_posix(),
                    )
                )
            self.assertEqual("STOP_REVIEW_LINEAGE_INVALID", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
