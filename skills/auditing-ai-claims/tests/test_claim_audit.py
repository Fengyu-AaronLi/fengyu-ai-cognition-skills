from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
RUNTIME_PATH = SKILL_DIR / "scripts" / "claim_audit.py"
BASE_INPUT = "The named paper exists."


def load_runtime():
    if not RUNTIME_PATH.is_file():
        raise AssertionError(f"missing executable runtime: {RUNTIME_PATH}")
    spec = importlib.util.spec_from_file_location("claim_audit", RUNTIME_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load claim_audit runtime")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def base_ledger() -> dict:
    return {
        "schema_version": "3.1",
        "audit_id": "audit-test",
        "created_at": "2026-08-05T10:00:00Z",
        "verification_date": "2026-08-05",
        "input": {
            "path": "input.txt",
            "sha256": hashlib.sha256(BASE_INPUT.encode("utf-8")).hexdigest(),
        },
        "scope": {
            "triggered": True,
            "reason": "named external claim",
            "unreviewed_claims": [],
            "candidate_inventory": [
                {
                    "candidate_id": "U001",
                    "text": BASE_INPUT,
                    "origin": "declared",
                    "sha256": hashlib.sha256(BASE_INPUT.encode("utf-8")).hexdigest(),
                    "spans": [{"start": 0, "end": len(BASE_INPUT)}],
                }
            ],
            "candidate_inventory_recorded": True,
        },
        "sources": [],
        "claims": [],
        "unknowns": ["none recorded"],
        "next_action": "open the highest-value primary source",
        "summary_recorded": True,
    }


def base_claim() -> dict:
    claim = {
        "claim_id": "C1",
        "text": "The named paper exists.",
        "claim_type": "existence_identity",
        "temporal_sensitivity": "low",
        "as_of": "2026-08-05",
        "criteria": {
            "defined": True,
            "conditions": ["publisher record matches title and authors"],
            "failure_condition": "publisher record conflicts",
        },
        "requires_independent_evidence": False,
        "risk_domain": "none",
        "causal_basis": "not_applicable",
        "evidence": [],
        "source_identity_gate": "unknown",
        "content_support_gate": "unknown",
        "action_applicability_gate": "not_applicable",
        "conflicts": [],
        "status": "unverifiable",
        "confidence_reason": "no source receipt",
        "next_step": "obtain the publisher record",
        "assessment_recorded": True,
        "unknowns": ["none recorded"],
        "input_candidates": [BASE_INPUT],
    }
    refresh_countercheck(claim)
    return claim


def refresh_countercheck(
    claim: dict, checked_source_ids: list[str] | None = None
) -> None:
    basis = copy.deepcopy(claim)
    basis.pop("countercheck", None)
    basis_hash = hashlib.sha256(
        json.dumps(
            basis,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    claim["countercheck"] = {
        "falsifier": "A primary record that contradicts the recorded assessment.",
        "checked_source_ids": list(checked_source_ids or []),
        "result": "inconclusive",
        "stop_reason": "No additional eligible contradicting record was available in this fixture.",
        "checked_at": "2026-08-05T10:10:00Z",
        "basis_hash": basis_hash,
    }


def record_countercheck_cli(
    workspace: Path,
    root: Path,
    claim_id: str = "C1",
    checked_source_ids: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    payload_path = root / f"countercheck-{claim_id}.json"
    payload_path.write_text(
        json.dumps(
            {
                "claim_id": claim_id,
                "falsifier": "A primary record that contradicts the current assessment.",
                "checked_source_ids": list(checked_source_ids or []),
                "result": "inconclusive",
                "stop_reason": "No additional eligible contradicting record was available in this test run.",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return subprocess.run(
        [
            sys.executable,
            str(RUNTIME_PATH),
            "countercheck",
            "--workspace",
            str(workspace),
            "--file",
            str(payload_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def valid_receipt(runtime, source_id: str = "S1", origin: str = "doi:example") -> dict:
    receipt = {
        "receipt_version": "1.0",
        "runtime_version": "3.1.0",
        "source_id": source_id,
        "requested_url": "https://example.com/source",
        "requested_url_query_sha256": None,
        "final_url": "https://example.com/source",
        "final_url_query_sha256": None,
        "resolved_ip": "93.184.216.34",
        "accessed_at": "2026-08-05T10:05:00Z",
        "http_status": 200,
        "content_type": "text/html",
        "content_encoding": "identity",
        "bytes_read": 128,
        "content_sha256": "a" * 64,
        "headers_sha256": "b" * 64,
        "redirect_chain": [],
        "origin_id": origin,
        "retrieval_complete": True,
        "support_eligible": True,
        "acquisition_type": "runtime_fetch",
        "transport_attestation": "dns_pinned_runtime",
        "artifact": "artifacts/source.bin",
        "parsed_text": "artifacts/source.txt",
        "parsed_text_sha256": "c" * 64,
        "parser_name": "html.parser",
        "parser_version": "3.1.0",
    }
    receipt["receipt_sha256"] = runtime.compute_receipt_sha256(receipt)
    return receipt


def attach_source_and_evidence(runtime, ledger: dict, claim: dict) -> dict:
    receipt = valid_receipt(runtime)
    ledger["sources"] = [
        {
            "source_id": "S1",
            "receipt": "receipts/S1.json",
            "source_tier": "A1",
            "evidence_role": "original_record",
            "publication_date": "2025-01-01",
            "freshness_status": "current",
            "freshness_rationale": "Opened the current source during this audit.",
            "origin_id": "doi:example",
        }
    ]
    claim["evidence"] = [
        {
            "source_id": "S1",
            "support": "direct",
            "evidence_purpose": "substantive",
            "support_scope": "the named paper and publisher record",
            "locator": "publisher metadata",
            "excerpt": "The named paper exists.",
            "inference_span": 0,
        }
    ]
    identity = copy.deepcopy(claim["evidence"][0])
    identity.update(
        evidence_purpose="source_identity",
        support_scope="the publisher record identity",
    )
    claim["evidence"].append(identity)
    currentness = copy.deepcopy(claim["evidence"][0])
    currentness.update(
        evidence_purpose="currentness",
        support_scope="the dated record current at the audit date",
    )
    claim["evidence"].append(currentness)
    refresh_countercheck(claim, ["S1"])
    return {"S1": receipt}


class RuntimeContractTests(unittest.TestCase):
    def test_runtime_exists_and_has_cli_help(self):
        self.assertTrue(RUNTIME_PATH.is_file(), "V2 requires an executable runtime")
        result = subprocess.run(
            [sys.executable, str(RUNTIME_PATH), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("init", result.stdout)
        self.assertIn("fetch", result.stdout)
        self.assertIn("check", result.stdout)
        self.assertIn("render", result.stdout)

    def test_confirmed_claim_without_receipt_fails_gate(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim.update(
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        ledger["claims"] = [claim]
        gate = runtime.validate_bundle(ledger, {})
        self.assertEqual(gate["verdict"], "FAIL")
        self.assertIn("SUBSTANTIVE_EVIDENCE_REQUIRED", {e["code"] for e in gate["errors"]})

    def test_tampered_receipt_fails_integrity_check(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        ledger["claims"] = [claim]
        receipts["S1"]["http_status"] = 404
        gate = runtime.validate_bundle(ledger, receipts)
        self.assertIn("RECEIPT_HASH_MISMATCH", {e["code"] for e in gate["errors"]})

    def test_high_temporal_claim_requires_as_of_date(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim["temporal_sensitivity"] = "high"
        claim["as_of"] = ""
        ledger["claims"] = [claim]
        gate = runtime.validate_bundle(ledger, {})
        self.assertIn("HIGH_TEMPORAL_WITHOUT_AS_OF", {e["code"] for e in gate["errors"]})

    def test_subject_self_report_cannot_satisfy_independence(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim.update(
            requires_independent_evidence=True,
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        ledger["sources"][0]["source_tier"] = "A2"
        ledger["sources"][0]["evidence_role"] = "subject_self_report"
        ledger["claims"] = [claim]
        gate = runtime.validate_bundle(ledger, receipts)
        self.assertIn("INDEPENDENCE_NOT_ESTABLISHED", {e["code"] for e in gate["errors"]})

    def test_duplicate_origin_does_not_become_two_independent_sources(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim.update(
            requires_independent_evidence=True,
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        second = copy.deepcopy(ledger["sources"][0])
        second.update(source_id="S2", receipt="receipts/S2.json", evidence_role="professional_analysis")
        ledger["sources"].append(second)
        receipt2 = valid_receipt(runtime, source_id="S2", origin="doi:example")
        receipts["S2"] = receipt2
        claim["evidence"].append(
            {
                "source_id": "S2",
                "support": "direct",
                "support_scope": "repeats the publisher record",
                "locator": "paragraph 2",
                "excerpt": "The report repeats the same record.",
                "inference_span": 0,
            }
        )
        ledger["claims"] = [claim]
        gate = runtime.validate_bundle(ledger, receipts)
        self.assertIn("INDEPENDENCE_NOT_ESTABLISHED", {e["code"] for e in gate["errors"]})

    def test_causal_confirmation_requires_causal_design(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim.update(claim_type="causal", causal_basis="none", status="confirmed")
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        ledger["claims"] = [claim]
        gate = runtime.validate_bundle(ledger, receipts)
        self.assertIn("CAUSALITY_NOT_ESTABLISHED", {e["code"] for e in gate["errors"]})

    def test_refuted_status_requires_conflict_evidence(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim["status"] = "refuted"
        ledger["claims"] = [claim]
        gate = runtime.validate_bundle(ledger, {})
        self.assertIn("REFUTED_WITHOUT_CONFLICT", {e["code"] for e in gate["errors"]})

    def test_high_risk_claim_cannot_pass_action_gate(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim.update(risk_domain="legal", action_applicability_gate="pass")
        ledger["claims"] = [claim]
        gate = runtime.validate_bundle(ledger, {})
        self.assertIn("PROFESSIONAL_BOUNDARY_REQUIRED", {e["code"] for e in gate["errors"]})

    def test_private_and_non_http_urls_are_blocked(self):
        runtime = load_runtime()
        with self.assertRaises(ValueError):
            runtime.assert_public_url("file:///etc/passwd")

        def private_resolver(host, port, type=None):
            return [(2, 1, 6, "", ("127.0.0.1", port))]

        with self.assertRaises(ValueError):
            runtime.assert_public_url("http://internal.example/secret", resolver=private_resolver)

    def test_oversized_response_is_rejected(self):
        runtime = load_runtime()
        with self.assertRaises(ValueError):
            runtime.read_limited(io.BytesIO(b"x" * 11), max_bytes=10)

    def test_receipt_path_cannot_escape_workspace(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with self.assertRaises(ValueError):
                runtime.safe_workspace_path(workspace, "../outside.json")

    def test_failed_gate_cannot_render_final_report(self):
        runtime = load_runtime()
        ledger = base_ledger()
        ledger["claims"] = [base_claim()]
        failed_gate = {
            "verdict": "FAIL",
            "errors": [{"code": "TEST", "path": "claims[0]", "message": "blocked"}],
            "warnings": [],
        }
        with self.assertRaises(ValueError):
            runtime.render_markdown(ledger, {}, failed_gate)

    def test_valid_confirmed_claim_passes_and_renders_receipt_hash(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim.update(
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        ledger["claims"] = [claim]
        gate = runtime.validate_bundle(ledger, receipts)
        self.assertEqual(gate["verdict"], "PASS", gate)
        gate["bundle_sha256"] = "c" * 64
        gate["warnings"].append(
            {
                "code": "TEST_WARNING",
                "path": "claims[0]",
                "message": "A visible warning for the report contract.",
            }
        )
        report = runtime.render_markdown(ledger, receipts, gate)
        self.assertIn(receipts["S1"]["receipt_sha256"], report)
        self.assertIn("来源日期", report)
        self.assertIn("A1", report)
        self.assertIn("来源身份门", report)
        self.assertIn("推断跨度", report)
        self.assertIn("当前未知", report)
        self.assertIn("最有效的下一步", report)
        self.assertIn("运行时结构门：PASS", report)
        self.assertIn("c" * 64, report)
        self.assertIn("证据附录", report)
        self.assertIn("TEST_WARNING", report)

    def test_report_has_clickable_sources_and_progressive_disclosure(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim.update(
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        ledger["claims"] = [claim]
        gate = runtime.validate_bundle(ledger, receipts)

        report = runtime.render_markdown(ledger, receipts, gate)

        self.assertIn(
            "| ID | 原子主张 | 状态 | 关键理由 | 当前未知 | 下一步 |",
            report,
        )
        self.assertIn("## 技术账本", report)
        self.assertIn("[S1](https://example.com/source)", report)
        self.assertNotIn("&lt;https://example.com/source&gt;", report)
        main_section = report.split("## 技术账本", 1)[0]
        self.assertNotIn("| 推断跨度 |", main_section)
        self.assertIn("The named paper exists.", report)
        self.assertIn("runtime_fetch", report)
        self.assertIn("Gate 警告", report)

    def test_report_lists_each_source_once_per_claim_section(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim.update(
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        ledger["claims"] = [claim]
        gate = runtime.validate_bundle(ledger, receipts)

        report = runtime.render_markdown(ledger, receipts, gate)
        main_section, technical_and_later = report.split("## 技术账本", 1)
        technical_section = technical_and_later.split("## 反证检查", 1)[0]
        source_link = "[S1](https://example.com/source)"

        self.assertEqual(main_section.count(source_link), 1)
        self.assertEqual(technical_section.count(source_link), 1)

    def test_report_marks_failed_fetch_receipts_as_ineligible(self):
        runtime = load_runtime()
        ledger = base_ledger()
        ledger["sources"] = [
            {
                "source_id": "S1",
                "receipt": "receipts/S1.json",
                "source_tier": "A1",
                "evidence_role": "original_record",
                "publication_date": "2025-01-01",
                "origin_id": "nist:ai-rmf",
                "freshness_status": "current",
            }
        ]
        receipt = valid_receipt(runtime)
        receipt["support_eligible"] = False
        receipt["fetch_error"] = "hostname did not resolve to a public address"
        receipt["receipt_sha256"] = runtime.compute_receipt_sha256(receipt)

        report = runtime.render_markdown(
            ledger,
            {"S1": receipt},
            {"verdict": "PASS", "errors": [], "warnings": []},
        )

        self.assertIn("可用于支持", report)
        self.assertIn("获取说明", report)
        self.assertIn("| 否 |", report)
        self.assertIn("hostname did not resolve to a public address", report)

    def test_init_check_nontrigger_route_does_not_render_audit_report(self):
        self.assertTrue(RUNTIME_PATH.is_file(), "V2 requires an executable runtime")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text(BASE_INPUT, encoding="utf-8")
            workspace = root / "audit-run"

            init_result = subprocess.run(
                [sys.executable, str(RUNTIME_PATH), "init", "--input", str(input_path), "--workspace", str(workspace)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(init_result.returncode, 0, init_result.stderr)
            self.assertTrue((workspace / "ledger.json").is_file())

            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            ledger["scope"].update(triggered=False, reason="creative writing only")
            ledger["unknowns"] = []
            ledger["next_action"] = "none"
            (workspace / "ledger.json").write_text(
                json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            check_result = subprocess.run(
                [sys.executable, str(RUNTIME_PATH), "check", "--workspace", str(workspace)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(check_result.returncode, 0, check_result.stderr)
            self.assertTrue((workspace / "gate.json").is_file())

            render_result = subprocess.run(
                [sys.executable, str(RUNTIME_PATH), "render", "--workspace", str(workspace)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(render_result.returncode, 0)
            self.assertFalse((workspace / "report.md").exists())

            next_result = subprocess.run(
                [sys.executable, str(RUNTIME_PATH), "next", "--workspace", str(workspace)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(next_result.returncode, 0, next_result.stderr)
            workflow = json.loads(next_result.stdout)
            self.assertEqual(workflow["stage"], "not_triggered")
            self.assertTrue(workflow["complete"])


if __name__ == "__main__":
    unittest.main()
