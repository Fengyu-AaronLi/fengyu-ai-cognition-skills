from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_claim_audit import RUNTIME_PATH, load_runtime, valid_receipt
from test_redteam_deadline_transaction_v3 import start_workspace
from test_runtime_integrity import make_complete_workspace


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class SourceTransactionAbortRedTests(unittest.TestCase):
    def test_next_exposes_an_executable_abort_recovery_action(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace, _, _ = make_complete_workspace(runtime, root)
            receipt = valid_receipt(
                runtime, source_id="S9", origin="dataset:example:partial"
            )
            source_record = runtime._source_ledger_record(
                "S9",
                "receipts/S9.json",
                tier="A1",
                role="original_record",
                published="2026-08-06",
                origin_id="dataset:example:partial",
                freshness_status="current",
                freshness_rationale="same-day original record",
            )
            runtime._begin_or_resume_source_transaction(
                workspace, source_record, receipt
            )

            result = run_cli("next", "--workspace", str(workspace))

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["stage"], "gate_repair")
            step = next(
                item
                for item in payload["next_steps"]
                if item["action"] == "abort_source_transaction"
            )
            self.assertEqual(step["cli_subcommand"], "abort-source-transaction")
            self.assertEqual(
                step["required_inputs"],
                ["--workspace", "--source-id", "--reason"],
            )
            self.assertEqual(step["source_id"], "S9")

    def test_prepared_transaction_can_be_aborted_without_erasing_the_trace(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_workspace(root)
            receipt = valid_receipt(
                runtime, source_id="S1", origin="dataset:example:source"
            )
            source_record = runtime._source_ledger_record(
                "S1",
                "receipts/S1.json",
                tier="A1",
                role="original_record",
                published="2026-08-06",
                origin_id="dataset:example:source",
                freshness_status="current",
                freshness_rationale="same-day original record",
            )
            transaction_path, transaction = runtime._begin_or_resume_source_transaction(
                workspace, source_record, receipt
            )
            self.assertEqual(transaction["status"], "prepared")
            before = transaction_path.read_bytes()
            self.assertIn(
                "SOURCE_TRANSACTION_INCOMPLETE",
                {
                    error["code"]
                    for error in runtime.validate_workspace(workspace)["errors"]
                },
            )

            aborted = run_cli(
                "abort-source-transaction",
                "--workspace",
                str(workspace),
                "--source-id",
                "S1",
                "--reason",
                "The process stopped before any immutable source artifact was saved, and the remote response can no longer be reproduced.",
            )

            self.assertEqual(aborted.returncode, 0, aborted.stderr)
            saved = json.loads(transaction_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "aborted")
            self.assertTrue(saved["abort_reason"].strip())
            self.assertTrue(saved["aborted_at"].strip())
            self.assertNotEqual(transaction_path.read_bytes(), before)
            self.assertEqual(
                json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))[
                    "sources"
                ],
                [],
            )
            codes = {
                error["code"]
                for error in runtime.validate_workspace(workspace)["errors"]
            }
            self.assertNotIn("SOURCE_TRANSACTION_INCOMPLETE", codes)

    def test_aborted_transaction_is_immutable_and_source_id_cannot_be_reused(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_workspace(root)
            receipt = valid_receipt(
                runtime, source_id="S1", origin="dataset:example:source"
            )
            source_record = runtime._source_ledger_record(
                "S1",
                "receipts/S1.json",
                tier="A1",
                role="original_record",
                published="2026-08-06",
                origin_id="dataset:example:source",
                freshness_status="current",
                freshness_rationale="same-day original record",
            )
            runtime._begin_or_resume_source_transaction(
                workspace, source_record, receipt
            )
            first = run_cli(
                "abort-source-transaction",
                "--workspace",
                str(workspace),
                "--source-id",
                "S1",
                "--reason",
                "The source acquisition cannot be reproduced after the crash.",
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            transaction_path = workspace / "source-transactions" / "S1.json"
            frozen = transaction_path.read_bytes()

            second = run_cli(
                "abort-source-transaction",
                "--workspace",
                str(workspace),
                "--source-id",
                "S1",
                "--reason",
                "A different reason must not rewrite the frozen abort record.",
            )

            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(transaction_path.read_bytes(), frozen)
            self.assertIn("already aborted", second.stderr)


if __name__ == "__main__":
    unittest.main()
