from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_claim_audit import RUNTIME_PATH, base_claim, load_runtime
from test_runtime_integrity import make_complete_workspace, write_json


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class StructuredWorkflowTests(unittest.TestCase):
    def test_scope_command_can_mark_non_trigger_without_manual_ledger_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "creative.txt"
            input_path.write_text("这是一个隐喻。", encoding="utf-8")
            workspace = root / "run"
            initialized = run_cli("init", "--input", str(input_path), "--workspace", str(workspace))
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            scoped = run_cli(
                "scope",
                "--workspace",
                str(workspace),
                "--not-triggered",
                "--reason",
                "creative metaphor only",
            )
            self.assertEqual(scoped.returncode, 0, scoped.stderr)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            self.assertFalse(ledger["scope"]["triggered"])
            self.assertEqual(ledger["claims"], [])

    def test_claim_command_adds_a_structured_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("A named paper exists.", encoding="utf-8")
            workspace = root / "run"
            self.assertEqual(
                run_cli("init", "--input", str(input_path), "--workspace", str(workspace)).returncode,
                0,
            )
            claim_path = root / "claim.json"
            claim = base_claim()
            write_json(claim_path, claim)
            added = run_cli("claim", "--workspace", str(workspace), "--file", str(claim_path))
            self.assertEqual(added.returncode, 0, added.stderr)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            self.assertEqual([item["claim_id"] for item in ledger["claims"]], ["C1"])

    def test_evidence_command_rejects_an_unknown_source_without_mutating_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("A named paper exists.", encoding="utf-8")
            workspace = root / "run"
            self.assertEqual(
                run_cli("init", "--input", str(input_path), "--workspace", str(workspace)).returncode,
                0,
            )
            claim_path = root / "claim.json"
            write_json(claim_path, base_claim())
            self.assertEqual(
                run_cli("claim", "--workspace", str(workspace), "--file", str(claim_path)).returncode,
                0,
            )
            before = (workspace / "ledger.json").read_bytes()
            evidence_path = root / "evidence.json"
            write_json(
                evidence_path,
                {
                    "claim_id": "C1",
                    "source_id": "S404",
                    "support": "direct",
                    "support_scope": "publisher record",
                    "locator": "paragraph 1",
                    "excerpt": "A named paper exists.",
                    "inference_span": 0,
                },
            )
            linked = run_cli("evidence", "--workspace", str(workspace), "--file", str(evidence_path))
            self.assertNotEqual(linked.returncode, 0)
            self.assertIn("unknown source", linked.stderr.lower())
            self.assertEqual(before, (workspace / "ledger.json").read_bytes())

    def test_assess_updates_decision_fields_without_erasing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("A named paper exists.", encoding="utf-8")
            workspace = root / "run"
            self.assertEqual(
                run_cli("init", "--input", str(input_path), "--workspace", str(workspace)).returncode,
                0,
            )
            claim = base_claim()
            claim["evidence"] = [{"source_id": "S1", "support": "context"}]
            claim_path = root / "claim.json"
            write_json(claim_path, claim)
            self.assertEqual(
                run_cli("claim", "--workspace", str(workspace), "--file", str(claim_path)).returncode,
                0,
            )
            assessment_path = root / "assessment.json"
            write_json(
                assessment_path,
                {
                    "claim_id": "C1",
                    "source_identity_gate": "unknown",
                    "content_support_gate": "unknown",
                    "action_applicability_gate": "not_applicable",
                    "status": "unverifiable",
                    "confidence_reason": "The original record is still missing.",
                    "conflicts": [],
                    "next_step": "Obtain the publisher record.",
                    "unknowns": ["The paper identity remains unverified."],
                    "next_action": "Resolve the DOI at the primary registry."
                },
            )
            assessed = run_cli(
                "assess", "--workspace", str(workspace), "--file", str(assessment_path)
            )
            self.assertEqual(assessed.returncode, 0, assessed.stderr)
            updated = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))["claims"][0]
            self.assertEqual(updated["evidence"], claim["evidence"])
            self.assertEqual(updated["confidence_reason"], "The original record is still missing.")

    def test_assess_requires_unknowns_and_global_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("A named paper exists.", encoding="utf-8")
            workspace = root / "run"
            self.assertEqual(
                run_cli("init", "--input", str(input_path), "--workspace", str(workspace)).returncode,
                0,
            )
            claim_path = root / "claim.json"
            write_json(claim_path, base_claim())
            self.assertEqual(
                run_cli("claim", "--workspace", str(workspace), "--file", str(claim_path)).returncode,
                0,
            )
            assessment_path = root / "assessment.json"
            write_json(
                assessment_path,
                {
                    "claim_id": "C1",
                    "source_identity_gate": "unknown",
                    "content_support_gate": "unknown",
                    "action_applicability_gate": "not_applicable",
                    "status": "unverifiable",
                    "confidence_reason": "The original record is still missing.",
                    "conflicts": [],
                    "next_step": "Obtain the publisher record.",
                },
            )

            assessed = run_cli(
                "assess", "--workspace", str(workspace), "--file", str(assessment_path)
            )

            self.assertNotEqual(assessed.returncode, 0)
            self.assertIn("next_action", assessed.stderr)
            self.assertIn("unknowns", assessed.stderr)

    def test_capture_records_browser_export_without_network_refetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("A named paper exists.", encoding="utf-8")
            source_path = root / "source.html"
            source_path.write_text("<p>A named paper exists.</p>", encoding="utf-8")
            workspace = root / "run"
            self.assertEqual(
                run_cli("init", "--input", str(input_path), "--workspace", str(workspace)).returncode,
                0,
            )
            captured = run_cli(
                "capture",
                "--workspace",
                str(workspace),
                "--source-id",
                "S1",
                "--file",
                str(source_path),
                "--requested-url",
                "https://example.com/source",
                "--final-url",
                "https://example.com/source",
                "--http-status",
                "200",
                "--content-type",
                "text/html; charset=utf-8",
                "--tier",
                "A1",
                "--role",
                "original_record",
                "--published",
                "2025-01-01",
                "--origin-id",
                "doi:example",
                "--acquisition-type",
                "browser_export",
            )
            self.assertNotEqual(captured.returncode, 0)
            receipt = json.loads((workspace / "receipts" / "S1.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["acquisition_type"], "browser_export")
            self.assertFalse(receipt["support_eligible"])
            self.assertIn("URL/content binding", receipt["ineligibility_reason"])
            self.assertTrue((workspace / receipt["artifact"]).is_file())

            located = run_cli(
                "quote",
                "--workspace",
                str(workspace),
                "--source-id",
                "S1",
                "--exact",
                "A named paper exists.",
            )
            self.assertEqual(located.returncode, 0, located.stderr)
            selector = json.loads(located.stdout)
            parsed = (workspace / receipt["parsed_text"]).read_text(encoding="utf-8")
            self.assertEqual(parsed[selector["start"] : selector["end"]], "A named paper exists.")
            self.assertEqual(len(selector["quote_sha256"]), 64)

            untrusted_path = root / "user-note.txt"
            untrusted_path.write_text("A copied sentence.", encoding="utf-8")
            untrusted = run_cli(
                "capture",
                "--workspace",
                str(workspace),
                "--source-id",
                "S2",
                "--file",
                str(untrusted_path),
                "--requested-url",
                "https://example.com/other",
                "--final-url",
                "https://example.com/other",
                "--http-status",
                "200",
                "--content-type",
                "text/plain; charset=utf-8",
                "--tier",
                "C",
                "--role",
                "lead_only",
                "--published",
                "unknown",
                "--origin-id",
                "user-note:other",
                "--acquisition-type",
                "user_supplied",
            )
            self.assertNotEqual(untrusted.returncode, 0)
            untrusted_receipt = json.loads(
                (workspace / "receipts" / "S2.json").read_text(encoding="utf-8")
            )
            self.assertFalse(untrusted_receipt["support_eligible"])

    def test_replay_reports_historical_integrity_but_not_current_freshness(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _, _ = make_complete_workspace(runtime, Path(tmp))
            self.assertEqual(run_cli("check", "--workspace", str(workspace)).returncode, 0)
            replayed = run_cli("replay", "--workspace", str(workspace))
            self.assertEqual(replayed.returncode, 0, replayed.stderr)
            payload = json.loads(replayed.stdout)
            self.assertEqual(payload["historical_integrity"], "PASS")
            self.assertFalse(payload["current_freshness_rechecked"])

            (workspace / "artifacts" / "S1.bin").write_bytes(b"tampered")
            failed = run_cli("replay", "--workspace", str(workspace))
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(json.loads(failed.stdout)["historical_integrity"], "FAIL")

    def test_failed_fetch_is_persisted_as_an_ineligible_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("A source exists.", encoding="utf-8")
            workspace = root / "run"
            self.assertEqual(
                run_cli("init", "--input", str(input_path), "--workspace", str(workspace)).returncode,
                0,
            )
            fetched = run_cli(
                "fetch",
                "--workspace",
                str(workspace),
                "--source-id",
                "Sbad",
                "--url",
                "file:///etc/passwd",
                "--tier",
                "C",
                "--role",
                "lead_only",
                "--published",
                "unknown",
                "--origin-id",
                "failed:file-url",
            )
            self.assertNotEqual(fetched.returncode, 0)
            receipt_path = workspace / "receipts" / "Sbad.json"
            self.assertTrue(receipt_path.is_file())
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertFalse(receipt["retrieval_complete"])
            self.assertFalse(receipt["support_eligible"])
            self.assertIn("only http and https", receipt["fetch_error"])


if __name__ == "__main__":
    unittest.main()
