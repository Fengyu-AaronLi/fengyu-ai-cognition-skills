from __future__ import annotations

import copy
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
)


def error_codes(gate: dict) -> set[str]:
    return {item.get("code") for item in gate.get("errors", [])}


class EvidencePurposeBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = load_runtime()

    def test_identity_gate_pass_requires_identity_purpose_excerpt(self):
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(self.runtime, ledger, claim)
        claim["evidence"] = [
            item
            for item in claim["evidence"]
            if item.get("evidence_purpose") == "substantive"
        ]
        claim.update(
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        ledger["claims"] = [claim]

        gate = self.runtime.validate_bundle(ledger, receipts)

        self.assertIn("SOURCE_IDENTITY_EVIDENCE_REQUIRED", error_codes(gate))

    def test_source_identity_excerpt_cannot_substitute_for_substantive_support(self):
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(self.runtime, ledger, claim)
        claim["evidence"][0]["evidence_purpose"] = "source_identity"
        claim.update(
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        ledger["claims"] = [claim]

        gate = self.runtime.validate_bundle(ledger, receipts)

        self.assertIn("SUBSTANTIVE_EVIDENCE_REQUIRED", error_codes(gate))

    def test_study_design_excerpt_alone_cannot_confirm_causal_effect(self):
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(self.runtime, ledger, claim)
        claim.update(
            claim_type="causal",
            causal_basis="randomized_controlled_trial",
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        claim["evidence"][0]["evidence_purpose"] = "study_design"
        identity = copy.deepcopy(claim["evidence"][0])
        identity["evidence_purpose"] = "source_identity"
        claim["evidence"].append(identity)
        ledger["claims"] = [claim]

        gate = self.runtime.validate_bundle(ledger, receipts)

        self.assertIn("SUBSTANTIVE_EVIDENCE_REQUIRED", error_codes(gate))

    def test_high_temporal_confirmation_requires_currentness_excerpt(self):
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(self.runtime, ledger, claim)
        claim["evidence"] = [
            item
            for item in claim["evidence"]
            if item.get("evidence_purpose") != "currentness"
        ]
        claim.update(
            temporal_sensitivity="high",
            as_of="2026-08-05",
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        identity = copy.deepcopy(claim["evidence"][0])
        identity["evidence_purpose"] = "source_identity"
        claim["evidence"].append(identity)
        ledger["claims"] = [claim]

        gate = self.runtime.validate_bundle(ledger, receipts)

        self.assertIn("CURRENTNESS_EVIDENCE_REQUIRED", error_codes(gate))


class CandidateExclusionBoundaryTests(unittest.TestCase):
    def test_declared_factual_candidate_cannot_be_reclassified_as_nonfactual(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = "The current CEO is Alice."
            input_path = root / "input.txt"
            input_path.write_text(candidate, encoding="utf-8")
            workspace = root / "audit"
            started = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME_PATH),
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "current identity claim",
                    "--candidate",
                    candidate,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(started.returncode, 0, started.stderr)

            excluded = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME_PATH),
                    "exclude-candidate",
                    "--workspace",
                    str(workspace),
                    "--candidate",
                    candidate,
                    "--classification",
                    "opinion",
                    "--reason",
                    "I choose to call it opinion.",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(excluded.returncode, 0)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            self.assertEqual(ledger["scope"]["unreviewed_claims"], [candidate])

    def test_report_discloses_every_excluded_input_unit(self):
        runtime = load_runtime()
        ledger = base_ledger()
        excluded_text = "I think the metaphor is beautiful."
        ledger["scope"]["candidate_inventory"].append(
            {
                "candidate_id": "U002",
                "text": excluded_text,
                "origin": "auto_gap",
                "sha256": runtime.sha256_bytes(excluded_text.encode("utf-8")),
                "spans": [{"start": 11, "end": 46}],
            }
        )
        ledger["scope"]["excluded_candidates"] = [
            {
                "candidate": excluded_text,
                "classification": "opinion",
                "reason": "A value judgment with no externally testable proposition.",
                "excluded_at": "2026-08-05T10:10:00Z",
            }
        ]
        ledger["claims"] = [base_claim()]

        report = runtime.render_markdown(
            ledger,
            {},
            {"verdict": "PASS", "bundle_sha256": "a" * 64},
        )

        self.assertIn("## 审计排除项", report)
        self.assertIn(excluded_text, report)
        self.assertIn("A value judgment with no externally testable proposition.", report)


if __name__ == "__main__":
    unittest.main()
