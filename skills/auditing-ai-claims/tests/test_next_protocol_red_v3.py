from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_claim_audit import RUNTIME_PATH, load_runtime
from test_runtime_integrity import make_complete_workspace, write_json


STATIC_SUBCOMMAND = re.compile(r"^[a-z][a-z0-9-]*$")
SHELL_FIELDS = {"argv", "command", "shell", "shell_command"}


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def start_legacy(root: Path, input_text: str, candidate: str) -> Path:
    input_path = root / "answer.txt"
    input_path.write_text(input_text, encoding="utf-8")
    workspace = root / "run"
    started = run_cli(
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
    if started.returncode != 0:
        raise AssertionError(started.stderr)
    return workspace


def claim_payload(candidate: str, *, causal: bool = False) -> dict:
    return {
        "claim_id": "C1",
        "text": candidate,
        "claim_type": "causal" if causal else "existence_identity",
        "temporal_sensitivity": "high" if causal else "low",
        "as_of": "2026-08-06",
        "criteria": {
            "defined": True,
            "conditions": ["An eligible original record directly supports the claim."],
            "failure_condition": "The eligible record contradicts the claim.",
        },
        "requires_independent_evidence": causal,
        "risk_domain": "none",
        "causal_basis": "none" if causal else "not_applicable",
        "evidence": [],
        "source_identity_gate": "unknown",
        "content_support_gate": "unknown",
        "action_applicability_gate": "not_applicable",
        "conflicts": [],
        "status": "current_unknown" if causal else "unverifiable",
        "confidence_reason": "No eligible opened source is linked yet.",
        "next_step": "Open the original study and its current record.",
        "input_candidates": [candidate],
    }


def add_claim_from_file(root: Path, workspace: Path, payload: dict) -> None:
    claim_path = root / "claim.json"
    write_json(claim_path, payload)
    added = run_cli("claim", "--workspace", str(workspace), "--file", str(claim_path))
    if added.returncode != 0:
        raise AssertionError(added.stderr)


def assert_machine_step(test: unittest.TestCase, step: dict) -> None:
    test.assertIsInstance(step.get("action"), str)
    test.assertIn("cli_subcommand", step)
    test.assertRegex(step["cli_subcommand"], STATIC_SUBCOMMAND)
    test.assertIn("required_inputs", step)
    test.assertIsInstance(step["required_inputs"], (list, dict))
    test.assertTrue(step["required_inputs"])
    test.assertTrue(SHELL_FIELDS.isdisjoint(step), step)


class NextSafeInputProtocolRedTests(unittest.TestCase):
    def test_start_accepts_candidates_file_json_without_candidate_cli_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = "The current CEO is Alice."
            input_path = root / "answer.txt"
            input_path.write_text(candidate, encoding="utf-8")
            candidates_path = root / "candidates.json"
            write_json(candidates_path, {"candidates": [candidate]})
            workspace = root / "run"

            started = run_cli(
                "start",
                "--input",
                str(input_path),
                "--workspace",
                str(workspace),
                "--as-of",
                "2026-08-06",
                "--reason",
                "externally verifiable claim",
                "--candidates-file",
                str(candidates_path),
            )

            self.assertEqual(started.returncode, 0, started.stderr)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            inventory = ledger["scope"]["candidate_inventory"]
            self.assertEqual(inventory[0]["candidate_id"], "U001")
            self.assertEqual(inventory[0]["text"], candidate)

    def test_next_claim_extraction_is_machine_executable_and_candidate_id_addressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_legacy(root, "A named paper exists.", "A named paper exists.")

            next_result = run_cli("next", "--workspace", str(workspace))

            self.assertEqual(next_result.returncode, 0, next_result.stderr)
            payload = json.loads(next_result.stdout)
            self.assertEqual(payload["stage"], "claim_extraction")
            step = payload["next_steps"][0]
            assert_machine_step(self, step)
            self.assertEqual(step["candidate_id"], "U001")
            self.assertIn(step["cli_subcommand"], {"claim", "exclude-candidate"})

    def test_next_assessment_names_claim_and_all_missing_evidence_purposes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = "The study proves AI causes universal cognitive decline."
            workspace = start_legacy(root, candidate, candidate)
            add_claim_from_file(root, workspace, claim_payload(candidate, causal=True))

            next_result = run_cli("next", "--workspace", str(workspace))

            self.assertEqual(next_result.returncode, 0, next_result.stderr)
            payload = json.loads(next_result.stdout)
            self.assertEqual(payload["stage"], "claim_assessment")
            step = payload["next_steps"][0]
            assert_machine_step(self, step)
            self.assertEqual(step["claim_id"], "C1")
            self.assertEqual(
                set(step["missing_evidence_purposes"]),
                {"substantive", "source_identity", "study_design", "currentness"},
            )

    def test_summarize_accepts_json_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = "A named paper exists."
            workspace = start_legacy(root, candidate, candidate)
            add_claim_from_file(root, workspace, claim_payload(candidate))
            assessment_path = root / "assessment.json"
            write_json(
                assessment_path,
                {
                    "claim_id": "C1",
                    "source_identity_gate": "unknown",
                    "content_support_gate": "unknown",
                    "action_applicability_gate": "not_applicable",
                    "status": "unverifiable",
                    "confidence_reason": "No eligible opened source was obtained.",
                    "conflicts": [],
                    "next_step": "Open the publisher record.",
                    "unknowns": ["The record identity remains unknown."],
                    "next_action": "Open the publisher record.",
                },
            )
            assessed = run_cli(
                "assess", "--workspace", str(workspace), "--file", str(assessment_path)
            )
            self.assertEqual(assessed.returncode, 0, assessed.stderr)
            countercheck_path = root / "countercheck.json"
            write_json(
                countercheck_path,
                {
                    "claim_id": "C1",
                    "falsifier": "A publisher record resolving the title to a different work.",
                    "checked_source_ids": [],
                    "result": "inconclusive",
                    "stop_reason": "No eligible publisher record was available in this run.",
                },
            )
            counterchecked = run_cli(
                "countercheck",
                "--workspace",
                str(workspace),
                "--file",
                str(countercheck_path),
            )
            self.assertEqual(counterchecked.returncode, 0, counterchecked.stderr)
            summary_path = root / "summary.json"
            write_json(
                summary_path,
                {
                    "unknowns": ["The record identity remains unknown."],
                    "next_action": "Open the publisher record.",
                },
            )

            summarized = run_cli(
                "summarize", "--workspace", str(workspace), "--file", str(summary_path)
            )

            self.assertEqual(summarized.returncode, 0, summarized.stderr)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            self.assertTrue(ledger["summary_recorded"])
            self.assertEqual(ledger["unknowns"], ["The record identity remains unknown."])

    def test_summarize_rejects_non_string_unknown_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = "A named paper exists."
            workspace = start_legacy(root, candidate, candidate)
            add_claim_from_file(root, workspace, claim_payload(candidate))
            assessment_path = root / "assessment.json"
            write_json(
                assessment_path,
                {
                    "claim_id": "C1",
                    "source_identity_gate": "unknown",
                    "content_support_gate": "unknown",
                    "action_applicability_gate": "not_applicable",
                    "status": "unverifiable",
                    "confidence_reason": "No eligible opened source was obtained.",
                    "conflicts": [],
                    "next_step": "Open the publisher record.",
                    "unknowns": ["The record identity remains unknown."],
                    "next_action": "Open the publisher record.",
                },
            )
            self.assertEqual(
                run_cli(
                    "assess",
                    "--workspace",
                    str(workspace),
                    "--file",
                    str(assessment_path),
                ).returncode,
                0,
            )
            countercheck_path = root / "countercheck.json"
            write_json(
                countercheck_path,
                {
                    "claim_id": "C1",
                    "falsifier": "A publisher record resolving to another work.",
                    "checked_source_ids": [],
                    "result": "inconclusive",
                    "stop_reason": "No eligible publisher record was available.",
                },
            )
            self.assertEqual(
                run_cli(
                    "countercheck",
                    "--workspace",
                    str(workspace),
                    "--file",
                    str(countercheck_path),
                ).returncode,
                0,
            )
            summary_path = root / "summary-invalid.json"
            write_json(
                summary_path,
                {"unknowns": [123], "next_action": "Open the publisher record."},
            )

            summarized = run_cli(
                "summarize", "--workspace", str(workspace), "--file", str(summary_path)
            )

            self.assertEqual(summarized.returncode, 1)
            self.assertIn("summary requires", summarized.stderr)
            self.assertNotIn("Traceback", summarized.stderr)

    def test_exclude_candidate_accepts_candidate_id_not_raw_candidate_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            declared = "The current CEO is Alice."
            auto_gap = "This is only a metaphor."
            workspace = start_legacy(root, f"{declared} {auto_gap}", declared)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            inventory = ledger["scope"]["candidate_inventory"]
            gap = next(item for item in inventory if item["origin"] == "auto_gap")

            excluded = run_cli(
                "exclude-candidate",
                "--workspace",
                str(workspace),
                "--candidate-id",
                gap["candidate_id"],
                "--classification",
                "metaphor",
                "--reason",
                "The sentence is explicitly framed as metaphorical.",
            )

            self.assertEqual(excluded.returncode, 0, excluded.stderr)
            updated = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            exclusion = updated["scope"]["excluded_candidates"][0]
            self.assertEqual(exclusion["candidate_id"], gap["candidate_id"])
            self.assertEqual(exclusion["candidate"], auto_gap)

    def test_next_never_embeds_candidate_or_excerpt_in_executable_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sentinel = root / "should-not-exist"
            dangerous_candidate = (
                f"The CEO is $(touch {sentinel}) and `id` with quote \"; rm marker."
            )
            workspace = start_legacy(root, dangerous_candidate, dangerous_candidate)

            extraction = json.loads(
                run_cli("next", "--workspace", str(workspace)).stdout
            )
            extraction_step = extraction["next_steps"][0]
            assert_machine_step(self, extraction_step)
            self.assertNotIn(dangerous_candidate, extraction_step["cli_subcommand"])
            self.assertNotIn(
                dangerous_candidate,
                json.dumps(extraction_step["required_inputs"], ensure_ascii=False),
            )

            runtime = load_runtime()
            evidence_root = root / "evidence-fixture"
            evidence_workspace, ledger, _ = make_complete_workspace(runtime, evidence_root)
            dangerous_excerpt = f"$(touch {sentinel}) ; `id` \"quoted\""
            ledger["claims"][0]["assessment_recorded"] = False
            ledger["claims"][0]["evidence"][0]["excerpt"] = dangerous_excerpt
            write_json(evidence_workspace / "ledger.json", ledger)

            assessment = json.loads(
                run_cli("next", "--workspace", str(evidence_workspace)).stdout
            )
            assessment_step = assessment["next_steps"][0]
            assert_machine_step(self, assessment_step)
            self.assertNotIn(dangerous_excerpt, assessment_step["cli_subcommand"])
            self.assertNotIn(
                dangerous_excerpt,
                json.dumps(assessment_step["required_inputs"], ensure_ascii=False),
            )
            self.assertFalse(sentinel.exists())


if __name__ == "__main__":
    unittest.main()
