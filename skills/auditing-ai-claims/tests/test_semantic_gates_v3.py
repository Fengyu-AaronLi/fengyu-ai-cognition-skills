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
    valid_receipt,
)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def add_claim(
    workspace: Path,
    *,
    claim_id: str,
    text: str,
    covers: list[str],
    keep_open: bool = False,
) -> subprocess.CompletedProcess[str]:
    args = [
        "add-claim",
        "--workspace",
        str(workspace),
        "--claim-id",
        claim_id,
        "--text",
        text,
        "--type",
        "existence_identity",
        "--temporal",
        "low",
        "--criterion",
        "An eligible original record directly supports this atomic claim.",
        "--failure-condition",
        "The original record directly conflicts with this atomic claim.",
        "--next-step",
        "Open the original record.",
    ]
    for candidate in covers:
        args.extend(["--covers", candidate])
    if keep_open:
        args.append("--keep-candidate-open")
    return run_cli(*args)


class CandidateBindingTests(unittest.TestCase):
    def test_start_auto_freezes_uncovered_input_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = "The named paper exists."
            omitted = "The current CEO is Alice."
            input_path = root / "answer.txt"
            input_path.write_text(f"{first} {omitted}", encoding="utf-8")
            workspace = root / "run"

            result = run_cli(
                "start",
                "--input",
                str(input_path),
                "--workspace",
                str(workspace),
                "--reason",
                "mixed external claims",
                "--candidate",
                first,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            self.assertEqual(
                ledger["scope"]["unreviewed_claims"], [first, omitted]
            )
            origins = {
                item["text"]: item["origin"]
                for item in ledger["scope"]["candidate_inventory"]
            }
            self.assertEqual(origins[first], "declared")
            self.assertEqual(origins[omitted], "auto_gap")

    def test_nonfactual_auto_gap_requires_explicit_exclusion_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fact = "The named paper exists."
            opinion = "I think the metaphor is beautiful."
            input_path = root / "answer.txt"
            input_path.write_text(f"{fact} {opinion}", encoding="utf-8")
            workspace = root / "run"
            started = run_cli(
                "start",
                "--input",
                str(input_path),
                "--workspace",
                str(workspace),
                "--reason",
                "one fact plus opinion",
                "--candidate",
                fact,
            )
            self.assertEqual(started.returncode, 0, started.stderr)

            missing_reason = run_cli(
                "exclude-candidate",
                "--workspace",
                str(workspace),
                "--candidate",
                opinion,
                "--classification",
                "opinion",
                "--reason",
                "",
            )
            self.assertNotEqual(missing_reason.returncode, 0)

            excluded = run_cli(
                "exclude-candidate",
                "--workspace",
                str(workspace),
                "--candidate",
                opinion,
                "--classification",
                "opinion",
                "--reason",
                "This sentence expresses a value judgment and contains no externally testable proposition.",
            )
            self.assertEqual(excluded.returncode, 0, excluded.stderr)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            self.assertEqual(ledger["scope"]["unreviewed_claims"], [fact])
            self.assertEqual(
                ledger["scope"]["excluded_candidates"][0]["classification"],
                "opinion",
            )

    def test_start_rejects_candidate_not_present_in_original_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("Model Z is currently the cheapest model.", encoding="utf-8")
            workspace = root / "run"

            result = run_cli(
                "start",
                "--input",
                str(input_path),
                "--workspace",
                str(workspace),
                "--reason",
                "current price claim",
                "--candidate",
                "The Moon is made of cheese.",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("original input", result.stderr.lower())
            self.assertFalse(workspace.exists(), "invalid start must fail before publishing a workspace")

    def test_candidate_inventory_records_replayable_input_selectors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = "The paper exists. It reports a 0.0% error rate."
            input_path = root / "answer.txt"
            input_path.write_text(text, encoding="utf-8")
            workspace = root / "run"
            candidate = "It reports a 0.0% error rate."

            result = run_cli(
                "start",
                "--input",
                str(input_path),
                "--workspace",
                str(workspace),
                "--reason",
                "research finding",
                "--candidate",
                candidate,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            item = ledger["scope"]["candidate_inventory"][0]
            start = text.index(candidate)
            self.assertEqual(item["text"], candidate)
            self.assertEqual(item["spans"], [{"start": start, "end": start + len(candidate)}])
            self.assertEqual(
                item["sha256"], hashlib.sha256(candidate.encode("utf-8")).hexdigest()
            )

    def test_one_claim_cannot_swallow_multiple_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = "The current CEO is Alice."
            second = "The current price is five dollars."
            input_path = root / "answer.txt"
            input_path.write_text(f"{first} {second}", encoding="utf-8")
            workspace = root / "run"
            started = run_cli(
                "start",
                "--input",
                str(input_path),
                "--workspace",
                str(workspace),
                "--reason",
                "two external claims",
                "--candidate",
                first,
                "--candidate",
                second,
            )
            self.assertEqual(started.returncode, 0, started.stderr)
            before = (workspace / "ledger.json").read_bytes()

            swallowed = add_claim(
                workspace,
                claim_id="C1",
                text=f"{first} {second}",
                covers=[first, second],
            )

            self.assertNotEqual(swallowed.returncode, 0)
            self.assertIn("exactly one", swallowed.stderr.lower())
            self.assertEqual((workspace / "ledger.json").read_bytes(), before)

    def test_one_compound_candidate_can_map_to_multiple_atomic_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = "The paper exists and reports a 0.0% error rate."
            input_path = root / "answer.txt"
            input_path.write_text(candidate, encoding="utf-8")
            workspace = root / "run"
            started = run_cli(
                "start",
                "--input",
                str(input_path),
                "--workspace",
                str(workspace),
                "--reason",
                "compound research sentence",
                "--candidate",
                candidate,
            )
            self.assertEqual(started.returncode, 0, started.stderr)

            first = add_claim(
                workspace,
                claim_id="C1",
                text="The paper exists",
                covers=[candidate],
                keep_open=True,
            )
            second = add_claim(
                workspace,
                claim_id="C2",
                text="reports a 0.0% error rate.",
                covers=[candidate],
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            self.assertEqual([item["claim_id"] for item in ledger["claims"]], ["C1", "C2"])
            self.assertEqual(ledger["scope"]["unreviewed_claims"], [])


class SemanticEvidenceGateTests(unittest.TestCase):
    def test_every_assessed_claim_requires_nonempty_unknown_reason_and_next_step(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim["unknowns"] = [""]
        claim["confidence_reason"] = ""
        claim["next_step"] = ""
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, {})

        codes = {item["code"] for item in gate["errors"]}
        self.assertIn("CLAIM_UNKNOWNS_REQUIRED", codes)
        self.assertIn("CONFIDENCE_REASON_REQUIRED", codes)
        self.assertIn("NEXT_STEP_REQUIRED", codes)

    def test_partially_supported_claim_cannot_hide_linked_conflict(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        claim["evidence"][0]["support"] = "partial"
        claim["evidence"].append(
            {
                "source_id": "S1",
                "support": "conflict",
                "support_scope": "the same audited scope",
                "locator": "paragraph 2",
                "excerpt": "The source reports the opposite result.",
                "inference_span": 0,
            }
        )
        claim.update(
            status="partially_supported",
            source_identity_gate="pass",
            content_support_gate="partial",
            conflicts=[],
        )
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, receipts)

        self.assertIn(
            "PARTIAL_DESPITE_UNRESOLVED_CONFLICT",
            {item["code"] for item in gate["errors"]},
        )

    def test_correlational_evidence_cannot_partially_support_literal_causal_claim(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        claim.update(
            claim_type="causal",
            causal_basis="cross_sectional_self_report",
            status="partially_supported",
            source_identity_gate="pass",
            content_support_gate="partial",
        )
        claim["evidence"][0].update(
            support="partial",
            support_scope="a self-reported association in the surveyed sample",
        )
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, receipts)

        self.assertIn(
            "CAUSALITY_NOT_ESTABLISHED",
            {item["code"] for item in gate["errors"]},
        )

    def test_causal_confirmation_requires_design_evidence_selector(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        claim.update(
            claim_type="causal",
            causal_basis="randomized_controlled_trial",
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        claim["evidence"][0]["evidence_purpose"] = "substantive"
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, receipts)

        self.assertIn(
            "CAUSAL_DESIGN_EVIDENCE_REQUIRED",
            {item["code"] for item in gate["errors"]},
        )

    def test_unknown_origins_never_establish_independence(self):
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
        ledger["sources"][0]["origin_id"] = "unknown:source-a"
        receipts["S1"]["origin_id"] = "unknown:source-a"
        receipts["S1"]["receipt_sha256"] = runtime.compute_receipt_sha256(receipts["S1"])

        second_source = copy.deepcopy(ledger["sources"][0])
        second_source.update(
            source_id="S2",
            receipt="receipts/S2.json",
            evidence_role="professional_analysis",
            origin_id="unknown:source-b",
        )
        ledger["sources"].append(second_source)
        second_receipt = valid_receipt(runtime, source_id="S2", origin="unknown:source-b")
        second_receipt["requested_url"] = "https://example.org/independent"
        second_receipt["final_url"] = "https://example.org/independent"
        second_receipt["content_sha256"] = "d" * 64
        second_receipt["receipt_sha256"] = runtime.compute_receipt_sha256(second_receipt)
        receipts["S2"] = second_receipt
        claim["evidence"].append(
            {
                "source_id": "S2",
                "support": "direct",
                "support_scope": "the same claim",
                "locator": "paragraph 1",
                "excerpt": "The named paper exists.",
                "inference_span": 0,
            }
        )
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, receipts)

        self.assertIn(
            "INDEPENDENCE_NOT_ESTABLISHED",
            {item["code"] for item in gate["errors"]},
        )

    def test_a2_material_cannot_confirm_objective_performance(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        ledger["sources"][0].update(
            source_tier="A2",
            evidence_role="original_record",
        )
        claim.update(
            claim_type="objective_performance",
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, receipts)

        self.assertIn(
            "VENDOR_SELF_REPORT_CANNOT_CONFIRM_OBJECTIVE_PERFORMANCE",
            {item["code"] for item in gate["errors"]},
        )


if __name__ == "__main__":
    unittest.main()
