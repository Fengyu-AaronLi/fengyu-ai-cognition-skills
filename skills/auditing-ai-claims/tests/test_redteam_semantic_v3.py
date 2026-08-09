from __future__ import annotations

import copy
import hashlib
import unittest
from unittest import mock

from test_claim_audit import (
    attach_source_and_evidence,
    base_claim,
    base_ledger,
    load_runtime,
    valid_receipt,
)


def error_codes(gate: dict) -> set[str]:
    return {item.get("code") for item in gate.get("errors", [])}


def bind_single_candidate(ledger: dict, text: str) -> None:
    ledger["input"]["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ledger["scope"]["candidate_inventory"] = [
        {
            "candidate_id": "U001",
            "text": text,
            "origin": "declared",
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "spans": [{"start": 0, "end": len(text)}],
        }
    ]
    ledger["scope"]["unreviewed_claims"] = []


def add_second_source(runtime, ledger: dict, receipts: dict) -> None:
    second = copy.deepcopy(ledger["sources"][0])
    second.update(
        source_id="S2",
        receipt="receipts/S2.json",
        publication_date="2025-01-02",
        origin_id="doi:second",
    )
    ledger["sources"].append(second)

    receipt = valid_receipt(runtime, source_id="S2", origin="doi:second")
    receipt.update(
        requested_url="https://second.example.net/source",
        final_url="https://second.example.net/source",
        content_sha256="d" * 64,
        parsed_text_sha256="e" * 64,
    )
    receipt["receipt_sha256"] = runtime.compute_receipt_sha256(receipt)
    receipts["S2"] = receipt


class SemanticBypassRedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = load_runtime()

    def test_narrow_claim_does_not_silently_close_compound_candidate(self):
        ledger = base_ledger()
        candidate = "The named paper exists and reports a 0.0% error rate."
        bind_single_candidate(ledger, candidate)
        claim = base_claim()
        claim.update(
            text="The named paper exists",
            input_candidates=[candidate],
        )
        ledger["claims"] = [claim]

        gate = self.runtime.validate_bundle(ledger, {})

        self.assertIn(
            "CANDIDATE_ATOMIC_COVERAGE_INCOMPLETE",
            error_codes(gate),
            "a narrow subspan must not silently account for the unclaimed remainder of a compound candidate",
        )

    def test_validate_bundle_rejects_duplicate_claim_ids(self):
        ledger = base_ledger()
        claim = base_claim()
        duplicate = copy.deepcopy(claim)
        ledger["claims"] = [claim, duplicate]

        gate = self.runtime.validate_bundle(ledger, {})

        self.assertIn("DUPLICATE_CLAIM_ID", error_codes(gate))

    def test_identity_and_substance_from_different_sources_do_not_combine(self):
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(self.runtime, ledger, claim)
        add_second_source(self.runtime, ledger, receipts)

        substantive = copy.deepcopy(claim["evidence"][0])
        substantive.update(source_id="S2", evidence_purpose="substantive")
        identity = copy.deepcopy(claim["evidence"][1])
        identity.update(source_id="S1", evidence_purpose="source_identity")
        claim["evidence"] = [substantive, identity]
        claim.update(
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        ledger["claims"] = [claim]

        gate = self.runtime.validate_bundle(ledger, receipts)

        self.assertIn("SOURCE_PURPOSE_BINDING_MISMATCH", error_codes(gate))

    def test_currentness_cannot_be_borrowed_from_another_source(self):
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(self.runtime, ledger, claim)
        add_second_source(self.runtime, ledger, receipts)

        substantive = copy.deepcopy(claim["evidence"][0])
        substantive.update(source_id="S1", evidence_purpose="substantive")
        identity = copy.deepcopy(claim["evidence"][1])
        identity.update(source_id="S1", evidence_purpose="source_identity")
        currentness = copy.deepcopy(claim["evidence"][2])
        currentness.update(source_id="S2", evidence_purpose="currentness")
        claim["evidence"] = [substantive, identity, currentness]
        claim.update(
            temporal_sensitivity="high",
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        ledger["claims"] = [claim]

        gate = self.runtime.validate_bundle(ledger, receipts)

        self.assertIn("SOURCE_PURPOSE_BINDING_MISMATCH", error_codes(gate))

    def test_study_design_cannot_be_borrowed_from_another_source(self):
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(self.runtime, ledger, claim)
        add_second_source(self.runtime, ledger, receipts)

        substantive = copy.deepcopy(claim["evidence"][0])
        substantive.update(source_id="S1", evidence_purpose="substantive")
        identity = copy.deepcopy(claim["evidence"][1])
        identity.update(source_id="S1", evidence_purpose="source_identity")
        design = copy.deepcopy(claim["evidence"][0])
        design.update(source_id="S2", evidence_purpose="study_design")
        claim["evidence"] = [substantive, identity, design]
        claim.update(
            claim_type="causal",
            causal_basis="randomized_controlled_trial",
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        ledger["claims"] = [claim]

        gate = self.runtime.validate_bundle(ledger, receipts)

        self.assertIn("SOURCE_PURPOSE_BINDING_MISMATCH", error_codes(gate))

    def test_pdf_magic_overrides_mislabeled_text_plain_and_fails_closed(self):
        payload = b"%PDF-1.7\nmalformed fixture\n%%EOF\n"
        failed_adapter_result = {
            "text": None,
            "parser_name": "pdftotext",
            "parser_version": "unavailable",
            "error": "pdftotext is not available",
        }

        with mock.patch.object(
            self.runtime,
            "parse_pdf_text",
            return_value=failed_adapter_result,
        ) as adapter:
            result = self.runtime.extract_evidence_text(
                payload,
                "text/plain; charset=utf-8",
            )

        adapter.assert_called_once_with(payload)
        self.assertEqual(result, failed_adapter_result)
        self.assertIsNone(result["text"])


if __name__ == "__main__":
    unittest.main()
