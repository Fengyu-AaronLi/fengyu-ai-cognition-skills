from __future__ import annotations

import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_claim_audit import (
    BASE_INPUT,
    RUNTIME_PATH,
    attach_source_and_evidence,
    base_claim,
    base_ledger,
    load_runtime,
    record_countercheck_cli,
    refresh_countercheck,
    valid_receipt,
)
from test_runtime_integrity import make_complete_workspace


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class ReleaseBlockerTests(unittest.TestCase):
    def test_workspace_is_private_and_self_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("A named paper exists.", encoding="utf-8")
            workspace = root / "run"

            initialized = run_cli(
                "init", "--input", str(input_path), "--workspace", str(workspace)
            )

            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            self.assertEqual(stat.S_IMODE(workspace.stat().st_mode), 0o700)
            self.assertTrue((workspace / ".gitignore").is_file())
            self.assertIn("*", (workspace / ".gitignore").read_text(encoding="utf-8"))
            for relative in ("input.txt", "ledger.json", "state.json", "events.jsonl"):
                self.assertEqual(stat.S_IMODE((workspace / relative).stat().st_mode), 0o600)

    def test_receipts_do_not_persist_secret_url_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("A named paper exists.", encoding="utf-8")
            source_path = root / "source.html"
            source_path.write_text("<p>A named paper exists.</p>", encoding="utf-8")
            workspace = root / "run"
            self.assertEqual(
                run_cli(
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "named paper claim",
                    "--candidate",
                    "A named paper exists.",
                ).returncode,
                0,
            )

            run_cli(
                "capture",
                "--workspace",
                str(workspace),
                "--source-id",
                "S1",
                "--file",
                str(source_path),
                "--requested-url",
                "https://example.com/paper?token=secret-token&download=1",
                "--final-url",
                "https://example.com/paper?token=secret-token&download=1",
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
                "example:paper",
                "--acquisition-type",
                "browser_export",
            )
            receipt_text = (workspace / "receipts" / "S1.json").read_text(encoding="utf-8")
            receipt = json.loads(receipt_text)

            self.assertNotIn("secret-token", receipt_text)
            self.assertEqual(receipt["requested_url"], "https://example.com/paper")
            self.assertEqual(len(receipt["requested_url_query_sha256"]), 64)

    def test_start_requires_an_explicit_candidate_claim_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("A named paper exists.", encoding="utf-8")

            started = run_cli(
                "start",
                "--input",
                str(input_path),
                "--workspace",
                str(root / "run"),
                "--reason",
                "named paper claim",
            )

            self.assertNotEqual(started.returncode, 0)
            self.assertIn("--candidate", started.stderr)

    def test_triggered_audit_without_claims_cannot_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("A named paper exists.", encoding="utf-8")
            workspace = root / "run"
            self.assertEqual(
                run_cli(
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "named paper claim",
                    "--candidate",
                    "A named paper exists.",
                ).returncode,
                0,
            )

            finished = run_cli("finish", "--workspace", str(workspace))

            self.assertNotEqual(finished.returncode, 0)
            self.assertIn("NO_CLAIMS_RECORDED", finished.stdout)
            self.assertFalse((workspace / "report.md").exists())

    def test_partially_supported_requires_usable_evidence_and_passing_identity(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim.update(
            status="partially_supported",
            source_identity_gate="unknown",
            content_support_gate="partial",
        )
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, {})
        codes = {error["code"] for error in gate["errors"]}

        self.assertIn("PARTIAL_WITHOUT_USABLE_EVIDENCE", codes)
        self.assertIn("PARTIAL_WITHOUT_PASSING_IDENTITY_GATE", codes)

    def test_external_capture_cannot_self_attest_url_content_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("NIST certified Model Q.", encoding="utf-8")
            fake_page = root / "fake-page.html"
            fake_page.write_text("<p>NIST certified Model Q.</p>", encoding="utf-8")
            workspace = root / "run"
            self.assertEqual(
                run_cli(
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "official certification claim",
                    "--candidate",
                    "NIST certified Model Q.",
                ).returncode,
                0,
            )

            captured = run_cli(
                "capture",
                "--workspace",
                str(workspace),
                "--source-id",
                "S1",
                "--file",
                str(fake_page),
                "--requested-url",
                "https://www.nist.gov/itl/ai-risk-management-framework",
                "--final-url",
                "https://www.nist.gov/itl/ai-risk-management-framework",
                "--http-status",
                "200",
                "--content-type",
                "text/html; charset=utf-8",
                "--tier",
                "A1",
                "--role",
                "regulatory_record",
                "--published",
                "2023-01-01",
                "--origin-id",
                "nist:ai-rmf",
                "--acquisition-type",
                "browser_export",
            )

            self.assertNotEqual(captured.returncode, 0)
            receipt = json.loads((workspace / "receipts" / "S1.json").read_text(encoding="utf-8"))
            self.assertFalse(receipt["support_eligible"])
            self.assertIn("binding", receipt["ineligibility_reason"].lower())

    def test_origin_labels_cannot_launder_same_transport_as_independent(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim["requires_independent_evidence"] = True
        claim.update(status="confirmed", source_identity_gate="pass", content_support_gate="pass")
        first = valid_receipt(runtime, source_id="S1", origin="origin:one")
        second = valid_receipt(runtime, source_id="S2", origin="origin:two")
        for receipt in (first, second):
            receipt.update(
                retrieval_complete=True,
                support_eligible=True,
                acquisition_type="runtime_fetch",
                artifact="artifacts/source.bin",
            )
            receipt["receipt_sha256"] = runtime.compute_receipt_sha256(receipt)
        ledger["sources"] = [
            {
                "source_id": "S1",
                "receipt": "receipts/S1.json",
                "source_tier": "A1",
                "evidence_role": "original_record",
                "publication_date": "2025-01-01",
                "freshness_status": "current",
                "origin_id": "origin:one",
            },
            {
                "source_id": "S2",
                "receipt": "receipts/S2.json",
                "source_tier": "A1",
                "evidence_role": "independent_replication",
                "publication_date": "2025-01-02",
                "freshness_status": "current",
                "origin_id": "origin:two",
            },
        ]
        claim["evidence"] = [
            {
                "source_id": source_id,
                "support": "direct",
                "support_scope": "the same copied result",
                "locator": "paragraph 1",
                "excerpt": "same copied result",
                "inference_span": 0,
            }
            for source_id in ("S1", "S2")
        ]
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, {"S1": first, "S2": second})

        self.assertIn(
            "INDEPENDENT_TRANSPORT_ROOTS_NOT_ESTABLISHED",
            {error["code"] for error in gate["errors"]},
        )

    def test_independence_requirement_does_not_block_honest_unknown(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim["requires_independent_evidence"] = True
        claim.update(
            status="unverifiable",
            source_identity_gate="unknown",
            content_support_gate="unknown",
        )
        refresh_countercheck(claim)
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, {})

        self.assertNotIn("INDEPENDENCE_NOT_ESTABLISHED", {e["code"] for e in gate["errors"]})
        self.assertEqual(gate["verdict"], "PASS", gate)

    def test_tier_c_lead_only_cannot_confirm_a_core_fact(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim.update(status="confirmed", source_identity_gate="pass", content_support_gate="pass")
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        receipt = receipts["S1"]
        receipt.update(
            retrieval_complete=True,
            support_eligible=True,
            acquisition_type="runtime_fetch",
            artifact="artifacts/S1.bin",
        )
        receipt["receipt_sha256"] = runtime.compute_receipt_sha256(receipt)
        ledger["sources"][0].update(source_tier="C", evidence_role="lead_only")
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, receipts)

        self.assertIn("LEAD_ONLY_CANNOT_CONFIRM", {e["code"] for e in gate["errors"]})

    def test_confirmed_claim_cannot_ignore_registered_conflict(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim.update(
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
            conflicts=["A comparable official record reports the opposite."],
        )
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        receipt = receipts["S1"]
        receipt.update(
            retrieval_complete=True,
            support_eligible=True,
            acquisition_type="runtime_fetch",
            artifact="artifacts/S1.bin",
        )
        receipt["receipt_sha256"] = runtime.compute_receipt_sha256(receipt)
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, receipts)

        self.assertIn("CONFIRMED_DESPITE_CONFLICT", {e["code"] for e in gate["errors"]})

    def test_invalid_claim_type_is_rejected_by_runtime_not_only_schema_file(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim["claim_type"] = "whatever_the_model_felt_like"
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, {})

        self.assertIn("CLAIM_TYPE_INVALID", {e["code"] for e in gate["errors"]})

    def test_input_tampering_breaks_replay_integrity(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _, _ = make_complete_workspace(runtime, Path(tmp))
            (workspace / "input.txt").write_text("changed input", encoding="utf-8")

            gate = runtime.validate_workspace(workspace)

            self.assertIn("INPUT_HASH_MISMATCH", {e["code"] for e in gate["errors"]})
            self.assertEqual(gate["verdict"], "FAIL")

    def test_status_marks_old_gate_and_report_stale_after_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("The named paper exists.", encoding="utf-8")
            workspace = root / "run"
            self.assertEqual(
                run_cli(
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "named paper claim",
                    "--candidate",
                    "The named paper exists.",
                ).returncode,
                0,
            )
            self.assertEqual(
                run_cli(
                    "add-claim",
                    "--workspace",
                    str(workspace),
                    "--claim-id",
                    "C1",
                    "--text",
                    "The named paper exists.",
                    "--type",
                    "existence_identity",
                    "--temporal",
                    "low",
                    "--criterion",
                    "A publisher record matches the identity fields.",
                    "--failure-condition",
                    "The record resolves to another object.",
                    "--next-step",
                    "Open the publisher record.",
                    "--covers",
                    "The named paper exists.",
                ).returncode,
                0,
            )
            self.assertEqual(
                run_cli(
                    "decide",
                    "--workspace",
                    str(workspace),
                    "--claim-id",
                    "C1",
                    "--identity-gate",
                    "unknown",
                    "--content-gate",
                    "unknown",
                    "--action-gate",
                    "not_applicable",
                    "--status",
                    "unverifiable",
                    "--confidence-reason",
                    "No eligible publisher record was obtained.",
                    "--next-step",
                    "Open the publisher record.",
                    "--unknown",
                    "The identity remains unverified.",
                    "--next-action",
                    "Resolve the named record.",
                ).returncode,
                0,
            )
            counterchecked = record_countercheck_cli(workspace, root)
            self.assertEqual(counterchecked.returncode, 0, counterchecked.stderr)
            summarized = run_cli(
                "summarize",
                "--workspace",
                str(workspace),
                "--unknown",
                "The identity remains unverified.",
                "--next-action",
                "Resolve the named record.",
            )
            self.assertEqual(summarized.returncode, 0, summarized.stderr)
            self.assertEqual(run_cli("finish", "--workspace", str(workspace)).returncode, 0)
            self.assertEqual(
                run_cli(
                    "add-claim",
                    "--workspace",
                    str(workspace),
                    "--claim-id",
                    "C1",
                    "--text",
                    "The named paper exists under the supplied identity fields.",
                    "--type",
                    "existence_identity",
                    "--temporal",
                    "low",
                    "--criterion",
                    "The publisher identity fields still match.",
                    "--failure-condition",
                    "The record resolves to another object.",
                    "--next-step",
                    "Re-open the publisher record.",
                    "--covers",
                    "The named paper exists.",
                    "--replace",
                ).returncode,
                0,
            )

            status = run_cli("status", "--workspace", str(workspace))
            payload = json.loads(status.stdout)

            self.assertEqual(payload["verdict"], "STALE")
            self.assertFalse(payload["gate_current"])
            self.assertNotIn("report", payload)
            self.assertNotIn("report_sha256", payload)

    def test_high_temporal_confirmation_rejects_old_access_labeled_current(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim.update(
            temporal_sensitivity="high",
            as_of="2026-08-05",
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        ledger["sources"][0]["freshness_status"] = "current"
        ledger["sources"][0]["freshness_rationale"] = "Caller labeled it current."
        receipts["S1"]["accessed_at"] = "2020-01-01T00:00:00Z"
        receipts["S1"]["receipt_sha256"] = runtime.compute_receipt_sha256(receipts["S1"])
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, receipts)

        self.assertIn(
            "CURRENT_SOURCE_ACCESS_DATE_MISMATCH",
            {error["code"] for error in gate["errors"]},
        )

    def test_high_temporal_confirmation_requires_freshness_rationale(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim.update(
            temporal_sensitivity="high",
            as_of="2026-08-05",
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        ledger["sources"][0]["freshness_status"] = "current"
        ledger["sources"][0]["freshness_rationale"] = ""
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, receipts)

        self.assertIn(
            "FRESHNESS_RATIONALE_REQUIRED",
            {error["code"] for error in gate["errors"]},
        )

    def test_multi_claim_audit_preserves_claim_unknowns_and_requires_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text(
                "Paper X exists. Paper X proves a universal causal effect.",
                encoding="utf-8",
            )
            workspace = root / "run"
            self.assertEqual(
                run_cli(
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "paper identity and causal conclusion",
                    "--candidate",
                    "Paper X exists.",
                    "--candidate",
                    "Paper X proves a universal causal effect.",
                ).returncode,
                0,
            )
            claims = [
                (
                    "C1",
                    "Paper X exists.",
                    "existence_identity",
                    "The paper identity remains unverified.",
                    "Resolve the DOI.",
                ),
                (
                    "C2",
                    "Paper X proves a universal causal effect.",
                    "causal",
                    "The research design remains unverified.",
                    "Open the methods section.",
                ),
            ]
            for claim_id, text_value, claim_type, unknown, next_action in claims:
                self.assertEqual(
                    run_cli(
                        "add-claim",
                        "--workspace",
                        str(workspace),
                        "--claim-id",
                        claim_id,
                        "--text",
                        text_value,
                        "--type",
                        claim_type,
                        "--temporal",
                        "low",
                        "--criterion",
                        "An original record directly supports this exact claim.",
                        "--failure-condition",
                        "The original record is absent or supports a narrower statement.",
                        "--next-step",
                        next_action,
                        "--covers",
                        text_value,
                    ).returncode,
                    0,
                )
                self.assertEqual(
                    run_cli(
                        "decide",
                        "--workspace",
                        str(workspace),
                        "--claim-id",
                        claim_id,
                        "--identity-gate",
                        "unknown",
                        "--content-gate",
                        "unknown",
                        "--action-gate",
                        "not_applicable",
                        "--status",
                        "unverifiable",
                        "--confidence-reason",
                        "No eligible original receipt was obtained.",
                        "--next-step",
                        next_action,
                        "--unknown",
                        unknown,
                        "--next-action",
                        next_action,
                    ).returncode,
                    0,
                )

            for claim_id, *_ in claims:
                counterchecked = record_countercheck_cli(
                    workspace, root, claim_id=claim_id
                )
                self.assertEqual(
                    counterchecked.returncode, 0, counterchecked.stderr
                )

            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            self.assertEqual(ledger["claims"][0].get("unknowns"), [claims[0][3]])
            self.assertEqual(ledger["claims"][1].get("unknowns"), [claims[1][3]])

            unfinished = run_cli("finish", "--workspace", str(workspace))
            self.assertNotEqual(unfinished.returncode, 0)
            self.assertIn("AUDIT_SUMMARY_REQUIRED", unfinished.stdout)

            summarized = run_cli(
                "summarize",
                "--workspace",
                str(workspace),
                "--unknown",
                claims[0][3],
                "--unknown",
                claims[1][3],
                "--next-action",
                "Resolve the DOI, then inspect the methods section.",
            )
            self.assertEqual(summarized.returncode, 0, summarized.stderr)
            self.assertEqual(run_cli("finish", "--workspace", str(workspace)).returncode, 0)

    def test_failed_fetch_redacts_secret_query_from_all_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("A named source exists.", encoding="utf-8")
            workspace = root / "run"
            secret = "secret-token-987"
            self.assertEqual(
                run_cli(
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "named source claim",
                    "--candidate",
                    "A named source exists.",
                ).returncode,
                0,
            )

            fetched = run_cli(
                "fetch",
                "--workspace",
                str(workspace),
                "--source-id",
                "S1",
                "--url",
                f"https://example.com/?token={secret} bad",
                "--tier",
                "A1",
                "--role",
                "original_record",
                "--published",
                "unknown",
                "--origin-id",
                "example:test",
            )

            persisted = "\n".join(
                [
                    (workspace / "receipts" / "S1.json").read_text(encoding="utf-8"),
                    (workspace / "events.jsonl").read_text(encoding="utf-8"),
                    fetched.stderr,
                ]
            )
            self.assertNotEqual(fetched.returncode, 0)
            self.assertNotIn(secret, persisted)

    def test_forged_runtime_fetch_without_artifacts_or_selector_fails_closed(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "run"
            (workspace / "receipts").mkdir(parents=True)
            (workspace / "input.txt").write_text(BASE_INPUT, encoding="utf-8")

            ledger = base_ledger()
            claim = base_claim()
            claim.update(
                status="confirmed",
                source_identity_gate="pass",
                content_support_gate="pass",
            )
            receipt = attach_source_and_evidence(runtime, ledger, claim)["S1"]
            ledger["claims"] = [claim]
            receipt.update(
                artifact=None,
                parsed_text=None,
                parsed_text_sha256=None,
                runtime_version="0.0-forged",
                transport_attestation="caller-says-runtime",
                acquisition_type="runtime_fetch",
                support_eligible=True,
                retrieval_complete=True,
            )
            receipt["receipt_sha256"] = runtime.compute_receipt_sha256(receipt)
            runtime._write_json(workspace / "ledger.json", ledger)
            runtime._write_json(workspace / "receipts" / "S1.json", receipt)

            gate = runtime.validate_workspace(workspace)
            codes = {error["code"] for error in gate["errors"]}
            self.assertEqual(gate["verdict"], "FAIL")
            self.assertIn("RUNTIME_ARTIFACT_REQUIRED", codes)
            self.assertIn("RUNTIME_PARSED_TEXT_REQUIRED", codes)
            self.assertIn("QUOTE_SELECTOR_REQUIRED", codes)

    def test_refutation_rejects_excessive_inference_span(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        claim["evidence"][0].update(support="conflict", inference_span=3)
        claim.update(
            status="refuted",
            source_identity_gate="pass",
            content_support_gate="fail",
            conflicts=["The source directly conflicts with the claim."],
        )
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, receipts)
        self.assertIn(
            "REFUTED_WITH_EXCESSIVE_INFERENCE",
            {error["code"] for error in gate["errors"]},
        )

    def test_status_fails_when_rendered_report_is_tampered(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _, _ = make_complete_workspace(runtime, Path(tmp))
            finished = run_cli("finish", "--workspace", str(workspace))
            self.assertEqual(finished.returncode, 0, finished.stderr)
            with (workspace / "report.md").open("a", encoding="utf-8") as handle:
                handle.write("\ntampered\n")

            status = run_cli("status", "--workspace", str(workspace))
            self.assertNotEqual(status.returncode, 0)
            payload = json.loads(status.stdout)
            self.assertFalse(payload["report_current"])
            self.assertEqual(payload["verdict"], "STALE")

    def test_capture_and_fetch_reject_traversal_source_id_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("A named paper exists.", encoding="utf-8")
            source_path = root / "source.html"
            source_path.write_text("<p>A named paper exists.</p>", encoding="utf-8")

            for operation in ("capture", "fetch"):
                with self.subTest(operation=operation):
                    workspace = root / f"run-{operation}"
                    started = run_cli(
                        "start",
                        "--input",
                        str(input_path),
                        "--workspace",
                        str(workspace),
                        "--reason",
                        "named paper claim",
                        "--candidate",
                        "A named paper exists.",
                    )
                    self.assertEqual(started.returncode, 0, started.stderr)
                    state_before = (workspace / "state.json").read_bytes()
                    ledger_before = (workspace / "ledger.json").read_bytes()

                    if operation == "capture":
                        result = run_cli(
                            "capture",
                            "--workspace",
                            str(workspace),
                            "--source-id",
                            "../state",
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
                            "example:source",
                            "--acquisition-type",
                            "browser_export",
                        )
                    else:
                        result = run_cli(
                            "fetch",
                            "--workspace",
                            str(workspace),
                            "--source-id",
                            "../state",
                            "--url",
                            "http://127.0.0.1/source",
                            "--tier",
                            "A1",
                            "--role",
                            "original_record",
                            "--published",
                            "2025-01-01",
                            "--origin-id",
                            "example:source",
                        )

                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual((workspace / "state.json").read_bytes(), state_before)
                    self.assertEqual((workspace / "ledger.json").read_bytes(), ledger_before)
                    self.assertEqual(list((workspace / "receipts").iterdir()), [])
                    self.assertFalse((workspace / "state.bin").exists())
                    self.assertFalse((workspace / "state.txt").exists())

    def test_source_ids_are_casefold_unique_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("A named source exists.", encoding="utf-8")
            first_source = root / "first.html"
            first_source.write_text("<p>first canonical source</p>", encoding="utf-8")
            replacement_source = root / "replacement.html"
            replacement_source.write_text("<p>replacement source</p>", encoding="utf-8")
            workspace = root / "run"
            self.assertEqual(
                run_cli(
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "named source claim",
                    "--candidate",
                    "A named source exists.",
                ).returncode,
                0,
            )
            first = run_cli(
                "capture",
                "--workspace",
                str(workspace),
                "--source-id",
                "S1",
                "--file",
                str(first_source),
                "--requested-url",
                "https://example.com/first",
                "--final-url",
                "https://example.com/first",
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
                "example:first",
                "--acquisition-type",
                "browser_export",
            )
            self.assertNotEqual(first.returncode, 0)
            tracked_paths = [
                workspace / "ledger.json",
                workspace / "state.json",
                workspace / "events.jsonl",
                workspace / "receipts" / "S1.json",
                workspace / "artifacts" / "S1.bin",
                workspace / "artifacts" / "S1.txt",
            ]
            before = {path: path.read_bytes() for path in tracked_paths}

            collision = run_cli(
                "capture",
                "--workspace",
                str(workspace),
                "--source-id",
                "s1",
                "--file",
                str(replacement_source),
                "--requested-url",
                "https://example.com/replacement",
                "--final-url",
                "https://example.com/replacement",
                "--http-status",
                "200",
                "--content-type",
                "text/html; charset=utf-8",
                "--tier",
                "A1",
                "--role",
                "original_record",
                "--published",
                "2025-01-02",
                "--origin-id",
                "example:replacement",
                "--acquisition-type",
                "browser_export",
            )

            self.assertNotEqual(collision.returncode, 0)
            for path, original in before.items():
                self.assertEqual(path.read_bytes(), original, path)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            self.assertEqual([source["source_id"] for source in ledger["sources"]], ["S1"])
            self.assertEqual(
                sorted(path.name for path in (workspace / "receipts").iterdir()),
                ["S1.json"],
            )
            self.assertEqual(
                sorted(path.name for path in (workspace / "artifacts").iterdir()),
                ["S1.bin", "S1.txt"],
            )

    def test_capture_and_fetch_refuse_preexisting_canonical_source_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("A named source exists.", encoding="utf-8")
            source_path = root / "source.html"
            source_path.write_text("<p>new source body</p>", encoding="utf-8")

            for operation in ("capture", "fetch"):
                for collision_relative in ("receipts/S1.json", "artifacts/S1.bin"):
                    with self.subTest(
                        operation=operation,
                        collision=collision_relative,
                    ):
                        suffix = collision_relative.replace("/", "-").replace(".", "-")
                        workspace = root / f"run-{operation}-{suffix}"
                        self.assertEqual(
                            run_cli(
                                "start",
                                "--input",
                                str(input_path),
                                "--workspace",
                                str(workspace),
                                "--reason",
                                "named source claim",
                                "--candidate",
                                "A named source exists.",
                            ).returncode,
                            0,
                        )
                        collision_path = workspace / collision_relative
                        sentinel = b"preexisting canonical source file"
                        collision_path.write_bytes(sentinel)
                        tracked = {
                            workspace / "ledger.json": (workspace / "ledger.json").read_bytes(),
                            workspace / "state.json": (workspace / "state.json").read_bytes(),
                            workspace / "events.jsonl": (workspace / "events.jsonl").read_bytes(),
                        }

                        if operation == "capture":
                            result = run_cli(
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
                                "example:source",
                                "--acquisition-type",
                                "browser_export",
                            )
                        else:
                            result = run_cli(
                                "fetch",
                                "--workspace",
                                str(workspace),
                                "--source-id",
                                "S1",
                                "--url",
                                "http://127.0.0.1/source",
                                "--tier",
                                "A1",
                                "--role",
                                "original_record",
                                "--published",
                                "2025-01-01",
                                "--origin-id",
                                "example:source",
                            )

                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(collision_path.read_bytes(), sentinel)
                        for path, original in tracked.items():
                            self.assertEqual(path.read_bytes(), original, path)
                        ledger = json.loads(
                            (workspace / "ledger.json").read_text(encoding="utf-8")
                        )
                        self.assertEqual(ledger["sources"], [])

    def test_status_detects_gate_verdict_tampering_as_integrity_failure(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _, _ = make_complete_workspace(runtime, Path(tmp))
            finished = run_cli("finish", "--workspace", str(workspace))
            self.assertEqual(finished.returncode, 0, finished.stderr)
            gate_path = workspace / "gate.json"
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
            self.assertEqual(gate["verdict"], "PASS")
            gate["verdict"] = "FAIL"
            gate_path.write_text(
                json.dumps(gate, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            status = run_cli("status", "--workspace", str(workspace))

            self.assertNotEqual(status.returncode, 0)
            payload = json.loads(status.stdout)
            self.assertEqual(payload.get("gate_integrity"), "FAIL")
            self.assertFalse(payload["gate_current"])
            self.assertEqual(payload["verdict"], "STALE")

    def test_legal_bundle_change_stales_custom_report_for_status_and_replay(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _, _ = make_complete_workspace(runtime, Path(tmp))
            custom_report = "reports/custom-audit.md"
            finished = run_cli(
                "finish",
                "--workspace",
                str(workspace),
                "--output",
                custom_report,
            )
            self.assertEqual(finished.returncode, 0, finished.stderr)
            self.assertTrue((workspace / custom_report).is_file())

            reassessed = run_cli(
                "decide",
                "--workspace",
                str(workspace),
                "--claim-id",
                "C1",
                "--identity-gate",
                "pass",
                "--content-gate",
                "pass",
                "--action-gate",
                "not_applicable",
                "--status",
                "confirmed",
                "--confidence-reason",
                "The same opened source was reassessed without changing its scope.",
                "--next-step",
                "Re-open the primary source if a fresh audit is required.",
                "--unknown",
                "No additional unknown recorded.",
                "--next-action",
                "Re-run the deterministic gate after this legal ledger update.",
            )
            self.assertEqual(reassessed.returncode, 0, reassessed.stderr)
            counterchecked = record_countercheck_cli(
                workspace, Path(tmp), checked_source_ids=["S1"]
            )
            self.assertEqual(counterchecked.returncode, 0, counterchecked.stderr)
            summarized = run_cli(
                "summarize",
                "--workspace",
                str(workspace),
                "--unknown",
                "No additional unknown recorded.",
                "--next-action",
                "Re-run the deterministic gate after this legal ledger update.",
            )
            self.assertEqual(summarized.returncode, 0, summarized.stderr)
            self.assertEqual(runtime.validate_workspace(workspace)["verdict"], "PASS")
            state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["stale_reports"][-1]["report"], custom_report)

            status = run_cli("status", "--workspace", str(workspace))
            replay = run_cli("replay", "--workspace", str(workspace))

            self.assertNotEqual(status.returncode, 0)
            self.assertEqual(json.loads(status.stdout)["verdict"], "STALE")
            self.assertNotEqual(replay.returncode, 0)
            replay_payload = json.loads(replay.stdout)
            self.assertEqual(replay_payload["historical_integrity"], "FAIL")
            self.assertIn(
                "GATE_STALE",
                {error["code"] for error in replay_payload["errors"]},
            )
            self.assertNotIn(
                replay_payload["report_integrity"],
                {"NOT_RENDERED", "PASS"},
            )

    def test_finish_cannot_overwrite_reserved_workspace_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("A named paper exists.", encoding="utf-8")
            workspace = root / "run"
            self.assertEqual(
                run_cli(
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "named paper",
                    "--candidate",
                    "A named paper exists.",
                ).returncode,
                0,
            )
            self.assertEqual(
                run_cli(
                    "add-claim",
                    "--workspace",
                    str(workspace),
                    "--claim-id",
                    "C1",
                    "--text",
                    "A named paper exists.",
                    "--type",
                    "existence_identity",
                    "--temporal",
                    "low",
                    "--criterion",
                    "An original publisher record matches the identity.",
                    "--failure-condition",
                    "The original record conflicts with the identity.",
                    "--next-step",
                    "Open the publisher record.",
                    "--covers",
                    "A named paper exists.",
                ).returncode,
                0,
            )
            self.assertEqual(
                run_cli(
                    "decide",
                    "--workspace",
                    str(workspace),
                    "--claim-id",
                    "C1",
                    "--identity-gate",
                    "unknown",
                    "--content-gate",
                    "unknown",
                    "--action-gate",
                    "not_applicable",
                    "--status",
                    "unverifiable",
                    "--confidence-reason",
                    "No eligible source was opened.",
                    "--next-step",
                    "Open the publisher record.",
                    "--unknown",
                    "The paper identity remains unknown.",
                    "--next-action",
                    "Open the publisher record.",
                ).returncode,
                0,
            )
            ignore_before = (workspace / ".gitignore").read_text(encoding="utf-8")

            finished = run_cli(
                "finish",
                "--workspace",
                str(workspace),
                "--output",
                ".gitignore",
            )

            self.assertNotEqual(finished.returncode, 0)
            self.assertEqual(
                (workspace / ".gitignore").read_text(encoding="utf-8"),
                ignore_before,
            )

    def test_high_temporal_partial_or_refuted_status_rejects_stale_evidence(self):
        runtime = load_runtime()
        for status in ("partially_supported", "refuted"):
            with self.subTest(status=status):
                ledger = base_ledger()
                claim = base_claim()
                receipts = attach_source_and_evidence(runtime, ledger, claim)
                claim.update(temporal_sensitivity="high", as_of=ledger["verification_date"])
                ledger["sources"][0]["freshness_status"] = "stale"
                if status == "partially_supported":
                    claim["evidence"][0]["support"] = "partial"
                    claim.update(
                        status=status,
                        source_identity_gate="pass",
                        content_support_gate="partial",
                    )
                else:
                    claim["evidence"][0]["support"] = "conflict"
                    claim.update(
                        status=status,
                        source_identity_gate="pass",
                        content_support_gate="fail",
                        conflicts=["The current claim conflicts with the source."],
                    )
                ledger["claims"] = [claim]

                gate = runtime.validate_bundle(ledger, receipts)
                self.assertIn(
                    "FRESHNESS_NOT_ESTABLISHED",
                    {error["code"] for error in gate["errors"]},
                )

    def test_refuted_status_cannot_ignore_usable_direct_support(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        direct = dict(claim["evidence"][0])
        conflict = dict(claim["evidence"][0])
        conflict["support"] = "conflict"
        claim["evidence"] = [direct, conflict]
        claim.update(
            status="refuted",
            source_identity_gate="pass",
            content_support_gate="fail",
            conflicts=["The same scope has both direct support and direct conflict."],
        )
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, receipts)
        self.assertIn(
            "REFUTED_DESPITE_DIRECT_SUPPORT",
            {error["code"] for error in gate["errors"]},
        )

    def test_loaded_runtime_receipt_rejects_private_url_and_boolean_byte_count(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim.update(
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        receipt = receipts["S1"]
        receipt["requested_url"] = "http://127.0.0.1/source"
        receipt["final_url"] = "http://127.0.0.1/source"
        receipt["bytes_read"] = True
        receipt["redirect_chain"] = [
            {
                "from": "https://example.com/source?token=hidden",
                "from_query_sha256": None,
                "to": "https://example.com/final",
                "to_query_sha256": None,
                "http_status": 302,
            }
        ]
        receipt["receipt_sha256"] = runtime.compute_receipt_sha256(receipt)
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, receipts)
        codes = {error["code"] for error in gate["errors"]}
        self.assertIn("RECEIPT_URL_UNSAFE", codes)
        self.assertIn("RECEIPT_BYTES_INVALID", codes)
        self.assertIn("RECEIPT_REDIRECT_URL_NOT_SANITIZED", codes)

    def test_rechecking_an_unchanged_finished_bundle_preserves_report_tracking(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _, _ = make_complete_workspace(runtime, Path(tmp))
            self.assertEqual(run_cli("finish", "--workspace", str(workspace)).returncode, 0)

            checked = run_cli("check", "--workspace", str(workspace))
            status = run_cli("status", "--workspace", str(workspace))
            replay = run_cli("replay", "--workspace", str(workspace))

            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(status.returncode, 0, status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertEqual(status_payload.get("report"), "report.md")
            self.assertTrue(status_payload.get("report_current"))
            self.assertEqual(
                json.loads(replay.stdout).get("report_integrity"),
                "PASS",
            )


if __name__ == "__main__":
    unittest.main()
