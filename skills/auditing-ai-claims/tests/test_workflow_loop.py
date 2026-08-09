from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_claim_audit import RUNTIME_PATH, record_countercheck_cli


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def start_workspace(root: Path, candidate: str) -> Path:
    input_path = root / "answer.txt"
    input_path.write_text(candidate, encoding="utf-8")
    workspace = root / "run"
    result = run_cli(
        "start",
        "--input",
        str(input_path),
        "--workspace",
        str(workspace),
        "--as-of",
        "2026-08-06",
        "--reason",
        "externally verifiable claim",
        "--candidate",
        candidate,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return workspace


def add_unknown_claim(workspace: Path, candidate: str) -> None:
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
        "Open the original record.",
        "--covers",
        candidate,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)


class WorkflowLoopTests(unittest.TestCase):
    def test_scope_cannot_replace_a_frozen_candidate_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = start_workspace(Path(tmp), "Candidate A.")
            ledger_path = workspace / "ledger.json"
            before = ledger_path.read_bytes()

            replaced = run_cli(
                "scope",
                "--workspace",
                str(workspace),
                "--triggered",
                "--reason",
                "replacement attempt",
                "--candidate",
                "Candidate B.",
            )

            self.assertNotEqual(replaced.returncode, 0)
            self.assertIn("frozen", replaced.stderr.lower())
            self.assertEqual(ledger_path.read_bytes(), before)

    def test_next_is_read_only_and_guides_claim_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = start_workspace(Path(tmp), "A named paper exists.")
            ledger_path = workspace / "ledger.json"
            before = file_sha256(ledger_path)

            result = run_cli("next", "--workspace", str(workspace))

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["complete"])
            self.assertEqual(payload["stage"], "claim_extraction")
            self.assertEqual(payload["next_steps"][0]["action"], "add_claim")
            self.assertEqual(payload["next_steps"][0]["candidate_id"], "U001")
            self.assertEqual(payload["next_steps"][0]["cli_subcommand"], "claim")
            self.assertNotIn("command", payload["next_steps"][0])
            required_fields = payload["next_steps"][0]["missing_fields"]
            self.assertEqual(len(required_fields), len(set(required_fields)))
            self.assertEqual(file_sha256(ledger_path), before)

    def test_next_routes_unassessed_claim_to_research_or_honest_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate = "A named paper exists."
            workspace = start_workspace(Path(tmp), candidate)
            add_unknown_claim(workspace, candidate)

            result = run_cli("next", "--workspace", str(workspace))

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["stage"], "claim_assessment")
            step = payload["next_steps"][0]
            self.assertEqual(step["action"], "assess")
            self.assertEqual(step["cli_subcommand"], "assess")
            self.assertEqual(step["claim_id"], "C1")
            self.assertIn("Open the original record", step["suggested_action"])

            status = run_cli("status", "--workspace", str(workspace))
            self.assertEqual(status.returncode, 0, status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertEqual(status_payload["workflow"]["stage"], "claim_assessment")
            self.assertEqual(
                status_payload["workflow"]["next_steps"][0]["claim_id"], "C1"
            )

    def test_rejected_source_can_be_retired_without_erasing_its_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate = "The current CEO is Alice."
            workspace = start_workspace(Path(tmp), candidate)
            add_unknown_claim(workspace, candidate)
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
            receipt_path = workspace / "receipts" / "S1.json"
            self.assertTrue(receipt_path.is_file())

            decided = run_cli(
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
                "The attempted target was rejected before retrieval.",
                "--next-step",
                "Open the official company record.",
                "--unknown",
                "The current CEO remains unknown.",
                "--next-action",
                "Open the official company record.",
            )
            self.assertEqual(decided.returncode, 0, decided.stderr)
            counterchecked = record_countercheck_cli(
                workspace, Path(tmp), checked_source_ids=["S1"]
            )
            self.assertEqual(counterchecked.returncode, 0, counterchecked.stderr)
            summarized = run_cli(
                "summarize",
                "--workspace",
                str(workspace),
                "--unknown",
                "The current CEO remains unknown.",
                "--next-action",
                "Open the official company record.",
            )
            self.assertEqual(summarized.returncode, 0, summarized.stderr)
            blocked = json.loads(run_cli("next", "--workspace", str(workspace)).stdout)
            self.assertEqual(blocked["stage"], "gate_repair")
            self.assertIn("S1", blocked["next_steps"][0]["recoverable_sources"])

            retired = run_cli(
                "retire-source",
                "--workspace",
                str(workspace),
                "--source-id",
                "S1",
                "--reason",
                "Runtime rejected the private target; retain only as a failed-attempt trace.",
            )
            self.assertEqual(retired.returncode, 0, retired.stderr)
            self.assertTrue(receipt_path.is_file(), "retirement must preserve the raw receipt")
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            self.assertFalse(ledger["sources"][0]["active"])
            counterchecked_after_retirement = record_countercheck_cli(
                workspace, Path(tmp)
            )
            self.assertEqual(
                counterchecked_after_retirement.returncode,
                0,
                counterchecked_after_retirement.stderr,
            )
            summarized_after_retirement = run_cli(
                "summarize",
                "--workspace",
                str(workspace),
                "--unknown",
                "The current CEO remains unknown.",
                "--next-action",
                "Open the official company record.",
            )
            self.assertEqual(
                summarized_after_retirement.returncode,
                0,
                summarized_after_retirement.stderr,
            )

            ready = json.loads(run_cli("next", "--workspace", str(workspace)).stdout)
            self.assertEqual(ready["next_steps"][0]["action"], "finish")
            finished = run_cli("finish", "--workspace", str(workspace))
            self.assertEqual(finished.returncode, 0, finished.stderr)

    def test_next_reports_complete_only_for_current_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate = "A named paper exists."
            workspace = start_workspace(Path(tmp), candidate)
            add_unknown_claim(workspace, candidate)
            decided = run_cli(
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
                "No eligible opened source was obtained.",
                "--next-step",
                "Open the original record.",
                "--unknown",
                "The record identity remains unknown.",
                "--next-action",
                "Open the original record.",
            )
            self.assertEqual(decided.returncode, 0, decided.stderr)
            counterchecked = record_countercheck_cli(workspace, Path(tmp))
            self.assertEqual(counterchecked.returncode, 0, counterchecked.stderr)
            summarized = run_cli(
                "summarize",
                "--workspace",
                str(workspace),
                "--unknown",
                "The record identity remains unknown.",
                "--next-action",
                "Open the original record.",
            )
            self.assertEqual(summarized.returncode, 0, summarized.stderr)

            before_finish = json.loads(run_cli("next", "--workspace", str(workspace)).stdout)
            self.assertFalse(before_finish["complete"])
            self.assertEqual(before_finish["next_steps"][0]["action"], "finish")

            finished = run_cli("finish", "--workspace", str(workspace))
            self.assertEqual(finished.returncode, 0, finished.stderr)
            after_finish = json.loads(run_cli("next", "--workspace", str(workspace)).stdout)
            self.assertTrue(after_finish["complete"])
            self.assertEqual(after_finish["stage"], "complete")
            self.assertEqual(after_finish["next_steps"], [])

            summarized = run_cli(
                "summarize",
                "--workspace",
                str(workspace),
                "--unknown",
                "The record identity remains unknown.",
                "--next-action",
                "Search the publisher registry again.",
            )
            self.assertEqual(summarized.returncode, 0, summarized.stderr)
            stale = json.loads(run_cli("next", "--workspace", str(workspace)).stdout)
            self.assertFalse(stale["complete"])
            self.assertEqual(stale["next_steps"][0]["action"], "finish")

    def test_next_never_interpolates_untrusted_text_into_a_shell_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / "should-not-run"
            candidate = f"The CEO is $(touch {sentinel})."
            workspace = start_workspace(Path(tmp), candidate)

            result = run_cli("next", "--workspace", str(workspace))

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            step = payload["next_steps"][0]
            self.assertEqual(step["candidate_id"], "U001")
            self.assertNotIn(candidate, json.dumps(step["required_inputs"], ensure_ascii=False))
            self.assertNotIn("command", step)
            self.assertFalse(sentinel.exists())


if __name__ == "__main__":
    unittest.main()
