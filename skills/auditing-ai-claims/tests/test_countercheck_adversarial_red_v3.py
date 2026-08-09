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
    base_claim,
    base_ledger,
    load_runtime,
    refresh_countercheck,
    valid_receipt,
)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def start_assessed_workspace(
    root: Path,
    *,
    status: str = "partially_supported",
) -> Path:
    candidate = "The named paper exists."
    input_path = root / "answer.txt"
    input_path.write_text(candidate, encoding="utf-8")
    workspace = root / "audit"
    started = run_cli(
        "start",
        "--input",
        str(input_path),
        "--workspace",
        str(workspace),
        "--as-of",
        "2026-08-06",
        "--reason",
        "externally verifiable existence claim",
        "--candidate",
        candidate,
    )
    if started.returncode != 0:
        raise AssertionError(started.stderr)
    added = run_cli(
        "add-claim",
        "--workspace",
        str(workspace),
        "--claim-id",
        "C1",
        "--text",
        candidate,
        "--type",
        "existence_identity",
        "--temporal",
        "low",
        "--criterion",
        "An eligible original record directly supports the identity.",
        "--failure-condition",
        "The publisher record resolves to a different identity.",
        "--next-step",
        "Open the original publisher record.",
        "--covers",
        candidate,
    )
    if added.returncode != 0:
        raise AssertionError(added.stderr)
    if status == "partially_supported":
        identity_gate = "unknown"
        content_gate = "partial"
        reason = "Only part of the identity is currently supported."
    else:
        identity_gate = "unknown"
        content_gate = "unknown"
        reason = "No eligible original record was obtained."
    assessed = run_cli(
        "decide",
        "--workspace",
        str(workspace),
        "--claim-id",
        "C1",
        "--identity-gate",
        identity_gate,
        "--content-gate",
        content_gate,
        "--action-gate",
        "not_applicable",
        "--status",
        status,
        "--confidence-reason",
        reason,
        "--next-step",
        "Open the original publisher record.",
        "--unknown",
        "Independent confirmation remains unavailable.",
        "--next-action",
        "Open the original publisher record.",
    )
    if assessed.returncode != 0:
        raise AssertionError(assessed.stderr)
    return workspace


def record_countercheck(
    root: Path,
    workspace: Path,
    *,
    checked_source_ids: list[str],
    result: str,
    falsifier: str = "A primary record that contradicts the current assessment.",
    stop_reason: str = "Standard countercheck completed; no further source was opened.",
) -> subprocess.CompletedProcess[str]:
    payload_path = root / "countercheck-adversarial.json"
    write_json(
        payload_path,
        {
            "claim_id": "C1",
            "falsifier": falsifier,
            "checked_source_ids": checked_source_ids,
            "result": result,
            "stop_reason": stop_reason,
        },
    )
    return run_cli(
        "countercheck",
        "--workspace",
        str(workspace),
        "--file",
        str(payload_path),
    )


def source_fixture(runtime, *, retired: bool = False) -> tuple[dict, dict]:
    source = {
        "source_id": "S1",
        "active": not retired,
        "receipt": "receipts/S1.json",
        "source_tier": "A1",
        "evidence_role": "original_record",
        "publication_date": "2025-01-01",
        "freshness_status": "current",
        "freshness_rationale": "Opened during the audit.",
        "origin_id": "doi:example",
    }
    if retired:
        source.update(
            retired_at="2026-08-06T02:00:00Z",
            retirement_reason="The source was retired after the countercheck.",
        )
    return source, valid_receipt(runtime)


def error_codes(gate: dict) -> set[str]:
    return {item.get("code") for item in gate.get("errors", [])}


class CountercheckAdversarialRedTests(unittest.TestCase):
    def test_decisive_status_cannot_close_countercheck_with_empty_source_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_assessed_workspace(root)

            checked = record_countercheck(
                root,
                workspace,
                checked_source_ids=[],
                result="inconclusive",
                stop_reason="No additional eligible contradicting record was available in this test run.",
            )

            self.assertNotEqual(checked.returncode, 0)
            next_result = run_cli("next", "--workspace", str(workspace))
            self.assertEqual(next_result.returncode, 0, next_result.stderr)
            self.assertEqual(json.loads(next_result.stdout)["stage"], "claim_countercheck")

    def test_failed_fetch_cannot_support_no_conflict_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_assessed_workspace(root)
            failed = run_cli(
                "fetch",
                "--workspace",
                str(workspace),
                "--source-id",
                "S1",
                "--url",
                "http://127.0.0.1/private",
                "--tier",
                "C",
                "--role",
                "lead_only",
                "--published",
                "unknown",
                "--origin-id",
                "rejected:private-target",
                "--freshness",
                "unknown",
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertTrue((workspace / "receipts" / "S1.json").is_file())

            checked = record_countercheck(
                root,
                workspace,
                checked_source_ids=["S1"],
                result="no_conflict_found",
            )

            self.assertNotEqual(checked.returncode, 0)

    def test_retired_checked_source_makes_countercheck_stale(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        source, receipt = source_fixture(runtime, retired=True)
        ledger["sources"] = [source]
        refresh_countercheck(claim, ["S1"])
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, {"S1": receipt})

        self.assertTrue(
            {
                "COUNTERCHECK_STALE",
                "COUNTERCHECK_SOURCE_UNAVAILABLE",
                "COUNTERCHECK_SOURCE_RETIRED",
            }
            & error_codes(gate)
        )

    def test_future_runtime_owned_checked_at_fails_validation(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim["countercheck"]["checked_at"] = "9999-01-01T00:00:00Z"
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, {})

        self.assertTrue(
            {
                "COUNTERCHECK_TIME_INVALID",
                "COUNTERCHECK_TIME_IN_FUTURE",
            }
            & error_codes(gate)
        )

    def test_conflict_found_requires_bound_conflict_evidence(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        source, receipt = source_fixture(runtime)
        ledger["sources"] = [source]
        refresh_countercheck(claim, ["S1"])
        claim["countercheck"]["result"] = "conflict_found"
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, {"S1": receipt})

        self.assertTrue(
            {
                "COUNTERCHECK_CONFLICT_UNBOUND",
                "COUNTERCHECK_CONFLICT_NOT_LINKED",
            }
            & error_codes(gate)
        )

    def test_scope_narrowed_requires_reassessment_before_summary(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        source, receipt = source_fixture(runtime)
        ledger["sources"] = [source]
        refresh_countercheck(claim, ["S1"])
        claim["countercheck"]["result"] = "scope_narrowed"
        ledger["claims"] = [claim]

        gate = runtime.validate_bundle(ledger, {"S1": receipt})

        self.assertTrue(
            {
                "COUNTERCHECK_REASSESSMENT_REQUIRED",
                "COUNTERCHECK_SCOPE_NARROWED_UNRESOLVED",
            }
            & error_codes(gate)
        )

    def test_countercheck_text_fields_are_size_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_assessed_workspace(root, status="unverifiable")

            checked = record_countercheck(
                root,
                workspace,
                checked_source_ids=[],
                result="inconclusive",
                falsifier="x" * 1_000_001,
                stop_reason="The source search stopped because no eligible record was available.",
            )

            self.assertNotEqual(checked.returncode, 0)
            self.assertTrue(
                "long" in checked.stderr.lower()
                or "size" in checked.stderr.lower()
                or "limit" in checked.stderr.lower()
            )

    def test_rendered_report_discloses_countercheck_record(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        ledger["claims"] = [claim]
        countercheck = claim["countercheck"]

        report = runtime.render_markdown(
            ledger,
            {},
            {"verdict": "PASS", "bundle_sha256": "a" * 64},
        )

        self.assertIn("## 反证检查", report)
        self.assertIn(countercheck["falsifier"], report)
        self.assertIn(countercheck["result"], report)
        self.assertIn(countercheck["stop_reason"], report)
        self.assertIn(countercheck["checked_at"], report)


if __name__ == "__main__":
    unittest.main()
