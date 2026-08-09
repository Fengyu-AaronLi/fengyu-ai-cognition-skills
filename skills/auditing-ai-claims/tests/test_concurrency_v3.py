from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from test_claim_audit import RUNTIME_PATH, load_runtime


def add_claim_command(workspace: Path, claim_id: str, candidate: str) -> list[str]:
    return [
        sys.executable,
        str(RUNTIME_PATH),
        "add-claim",
        "--workspace",
        str(workspace),
        "--claim-id",
        claim_id,
        "--text",
        candidate,
        "--type",
        "existence_identity",
        "--temporal",
        "low",
        "--criterion",
        "An eligible original record directly supports this claim.",
        "--failure-condition",
        "The original record directly conflicts with this claim.",
        "--next-step",
        "Open the original record.",
        "--covers",
        candidate,
    ]


class WorkspaceConcurrencyTests(unittest.TestCase):
    def test_concurrent_start_has_exactly_one_workspace_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_input = root / "first.txt"
            second_input = root / "second.txt"
            first_input.write_text("Paper A exists.", encoding="utf-8")
            second_input.write_text("Paper B exists.", encoding="utf-8")
            workspace = root / "audit"

            commands = [
                [
                    sys.executable,
                    str(RUNTIME_PATH),
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "concurrent initialization",
                    "--candidate",
                    candidate,
                ]
                for input_path, candidate in (
                    (first_input, "Paper A exists."),
                    (second_input, "Paper B exists."),
                )
            ]
            processes = [
                subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for command in commands
            ]
            outputs = [process.communicate(timeout=10) for process in processes]

            self.assertEqual(
                sorted(process.returncode for process in processes), [0, 1], outputs
            )
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            saved_input = (workspace / "input.txt").read_text(encoding="utf-8")
            candidates = {
                item["text"] for item in ledger["scope"]["candidate_inventory"]
            }
            self.assertIn(saved_input, {"Paper A exists.", "Paper B exists."})
            self.assertEqual(candidates, {saved_input})
            init_record = json.loads(
                (workspace / ".runtime-init.json").read_text(encoding="utf-8")
            )
            self.assertEqual(init_record["audit_id"], ledger["audit_id"])

    def test_concurrent_writers_serialize_without_lost_claims(self):
        runtime = load_runtime()
        self.assertTrue(
            hasattr(runtime, "workspace_lock"),
            "runtime must expose the same workspace lock used by CLI dispatch",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = "Paper A exists."
            second = "Paper B exists."
            input_path = root / "input.txt"
            input_path.write_text(f"{first} {second}", encoding="utf-8")
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
                    "two paper identity claims",
                    "--candidate",
                    first,
                    "--candidate",
                    second,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(started.returncode, 0, started.stderr)

            with runtime.workspace_lock(workspace, exclusive=True):
                process_one = subprocess.Popen(
                    add_claim_command(workspace, "C1", first),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                process_two = subprocess.Popen(
                    add_claim_command(workspace, "C2", second),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                time.sleep(0.2)
                self.assertIsNone(process_one.poll())
                self.assertIsNone(process_two.poll())

            stdout_one, stderr_one = process_one.communicate(timeout=10)
            stdout_two, stderr_two = process_two.communicate(timeout=10)
            self.assertEqual(process_one.returncode, 0, stderr_one or stdout_one)
            self.assertEqual(process_two.returncode, 0, stderr_two or stdout_two)

            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            self.assertEqual(
                {claim["claim_id"] for claim in ledger["claims"]},
                {"C1", "C2"},
            )
            self.assertEqual(ledger["scope"]["unreviewed_claims"], [])


if __name__ == "__main__":
    unittest.main()
