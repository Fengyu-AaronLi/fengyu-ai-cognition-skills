from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from test_claim_audit import RUNTIME_PATH


COUNTERCHECK_INPUT_FIELDS = {
    "claim_id",
    "falsifier",
    "checked_source_ids",
    "result",
    "stop_reason",
}
COUNTERCHECK_GENERATED_FIELDS = {"checked_at", "basis_hash"}


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


def start_workspace(root: Path, candidate: str = "The named paper exists.") -> Path:
    input_path = root / "answer.txt"
    input_path.write_text(candidate, encoding="utf-8")
    workspace = root / "audit"
    result = run_cli(
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
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    result = run_cli(
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
        "The supplied identity resolves to a different record.",
        "--next-step",
        "Open the original publisher record.",
        "--covers",
        candidate,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return workspace


def decide(
    workspace: Path,
    *,
    status: str = "partially_supported",
    confidence_reason: str = "The available trace supports only part of the claim.",
) -> subprocess.CompletedProcess[str]:
    return run_cli(
        "decide",
        "--workspace",
        str(workspace),
        "--claim-id",
        "C1",
        "--identity-gate",
        "unknown",
        "--content-gate",
        "partial" if status == "partially_supported" else "unknown",
        "--action-gate",
        "not_applicable",
        "--status",
        status,
        "--confidence-reason",
        confidence_reason,
        "--next-step",
        "Open the original publisher record.",
        "--unknown",
        "Independent confirmation remains unavailable.",
        "--next-action",
        "Open the original publisher record.",
    )


def record_countercheck(
    root: Path,
    workspace: Path,
    *,
    checked_source_ids: list[str] | None = None,
    result: str = "inconclusive",
    stop_reason: str = "No additional eligible primary source was available in this run.",
) -> subprocess.CompletedProcess[str]:
    payload = {
        "claim_id": "C1",
        "falsifier": "A publisher record showing a different title, authors, or identifier.",
        "checked_source_ids": list(checked_source_ids or []),
        "result": result,
        "stop_reason": stop_reason,
    }
    payload_path = root / "countercheck.json"
    write_json(payload_path, payload)
    return run_cli(
        "countercheck",
        "--workspace",
        str(workspace),
        "--file",
        str(payload_path),
    )


def next_payload(workspace: Path) -> dict:
    result = run_cli("next", "--workspace", str(workspace))
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def assert_countercheck_transition(test: unittest.TestCase, payload: dict) -> None:
    test.assertEqual(payload["stage"], "claim_countercheck")
    steps = [
        item
        for item in payload["next_steps"]
        if item.get("claim_id") == "C1" and item.get("action") == "countercheck"
    ]
    test.assertEqual(len(steps), 1, payload)
    step = steps[0]
    test.assertEqual(step.get("cli_subcommand"), "countercheck")
    test.assertTrue(
        COUNTERCHECK_INPUT_FIELDS - {"claim_id"} <= set(step.get("missing_fields", [])),
        step,
    )
    test.assertEqual(step.get("required_options"), ["--workspace", "--file"])
    test.assertTrue(
        COUNTERCHECK_GENERATED_FIELDS <= set(step.get("runtime_generated_fields", [])),
        step,
    )


class CountercheckStateMachineRedTests(unittest.TestCase):
    def test_decisive_assessment_routes_to_executable_countercheck_before_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_workspace(root)
            assessed = decide(workspace)
            self.assertEqual(assessed.returncode, 0, assessed.stderr)

            assert_countercheck_transition(self, next_payload(workspace))

    def test_direct_summary_cannot_bypass_missing_decisive_countercheck(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_workspace(root)
            assessed = decide(workspace, status="refuted")
            self.assertEqual(assessed.returncode, 0, assessed.stderr)

            summarized = run_cli(
                "summarize",
                "--workspace",
                str(workspace),
                "--unknown",
                "No remaining unknowns recorded.",
                "--next-action",
                "No further action.",
            )

            self.assertNotEqual(summarized.returncode, 0)
            self.assertIn("countercheck", summarized.stderr.lower())

    def test_unverifiable_countercheck_accepts_explicit_stop_and_is_runtime_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_workspace(root)
            assessed = decide(
                workspace,
                status="unverifiable",
                confidence_reason="No eligible opened source was obtained.",
            )
            self.assertEqual(assessed.returncode, 0, assessed.stderr)

            checked = record_countercheck(root, workspace)
            self.assertEqual(checked.returncode, 0, checked.stderr)

            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            record = ledger["claims"][0]["countercheck"]
            self.assertEqual(record["checked_source_ids"], [])
            self.assertEqual(record["result"], "inconclusive")
            self.assertTrue(record["stop_reason"].strip())
            self.assertRegex(record["basis_hash"], r"^[a-f0-9]{64}$")
            self.assertIsNotNone(
                datetime.fromisoformat(record["checked_at"].replace("Z", "+00:00"))
            )

    def test_unverifiable_countercheck_rejects_blank_stop_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_workspace(root)
            assessed = decide(
                workspace,
                status="unverifiable",
                confidence_reason="No eligible opened source was obtained.",
            )
            self.assertEqual(assessed.returncode, 0, assessed.stderr)

            checked = record_countercheck(root, workspace, stop_reason="   ")

            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("stop_reason", checked.stderr)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            self.assertNotIn("countercheck", ledger["claims"][0])

    def test_assessment_change_makes_prior_countercheck_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_workspace(root)
            assessed = decide(
                workspace,
                status="unverifiable",
                confidence_reason="No eligible opened source was obtained.",
            )
            self.assertEqual(assessed.returncode, 0, assessed.stderr)
            checked = record_countercheck(root, workspace)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertNotEqual(next_payload(workspace)["stage"], "claim_countercheck")

            reassessed = decide(
                workspace,
                status="unverifiable",
                confidence_reason="A changed assessment now makes a narrower inference.",
            )
            self.assertEqual(reassessed.returncode, 0, reassessed.stderr)

            assert_countercheck_transition(self, next_payload(workspace))

    def test_evidence_change_makes_prior_countercheck_stale_after_reassessment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_workspace(root)
            source_path = root / "source.txt"
            source_path.write_text(
                "Publisher context for the named paper.", encoding="utf-8"
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
                "https://publisher.example/paper",
                "--final-url",
                "https://publisher.example/paper",
                "--http-status",
                "200",
                "--content-type",
                "text/plain",
                "--tier",
                "A1",
                "--role",
                "original_record",
                "--published",
                "2026-08-06",
                "--origin-id",
                "publisher:paper",
                "--acquisition-type",
                "user_supplied",
                "--freshness",
                "current",
                "--freshness-rationale",
                "Captured on the audit date.",
            )
            self.assertNotEqual(captured.returncode, 0)
            self.assertTrue((workspace / "receipts" / "S1.json").is_file())
            assessed = decide(workspace)
            self.assertEqual(assessed.returncode, 0, assessed.stderr)
            checked = record_countercheck(root, workspace, checked_source_ids=["S1"])
            self.assertEqual(checked.returncode, 0, checked.stderr)

            linked = run_cli(
                "link",
                "--workspace",
                str(workspace),
                "--claim-id",
                "C1",
                "--source-id",
                "S1",
                "--support",
                "context",
                "--purpose",
                "substantive",
                "--support-scope",
                "Publisher context only.",
                "--excerpt",
                "Publisher context for the named paper.",
                "--locator",
                "imported text",
                "--inference-span",
                "0",
            )
            self.assertEqual(linked.returncode, 0, linked.stderr)
            reassessed = decide(
                workspace,
                confidence_reason="The new contextual evidence does not directly settle the claim.",
            )
            self.assertEqual(reassessed.returncode, 0, reassessed.stderr)

            assert_countercheck_transition(self, next_payload(workspace))

    def test_claim_change_cannot_reuse_old_basis_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_workspace(root)
            assessed = decide(
                workspace,
                status="unverifiable",
                confidence_reason="No eligible opened source was obtained.",
            )
            self.assertEqual(assessed.returncode, 0, assessed.stderr)
            checked = record_countercheck(root, workspace)
            self.assertEqual(checked.returncode, 0, checked.stderr)

            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            replacement = ledger["claims"][0]
            old_hash = replacement["countercheck"]["basis_hash"]
            replacement["criteria"]["failure_condition"] = (
                "The publisher or DOI registry identifies a different record."
            )
            replacement_path = root / "replacement-claim.json"
            write_json(replacement_path, replacement)
            replaced = run_cli(
                "claim",
                "--workspace",
                str(workspace),
                "--file",
                str(replacement_path),
                "--replace",
            )
            self.assertEqual(replaced.returncode, 0, replaced.stderr)
            reassessed = decide(
                workspace,
                status="unverifiable",
                confidence_reason="No eligible opened source was obtained after replacement.",
            )
            self.assertEqual(reassessed.returncode, 0, reassessed.stderr)

            payload = next_payload(workspace)
            assert_countercheck_transition(self, payload)
            current = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            record = current["claims"][0].get("countercheck")
            self.assertTrue(
                record is None
                or record.get("basis_hash") != old_hash
                or record.get("stale") is True
            )


if __name__ == "__main__":
    unittest.main()
