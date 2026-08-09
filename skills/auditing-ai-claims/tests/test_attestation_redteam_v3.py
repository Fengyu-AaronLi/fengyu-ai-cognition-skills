from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_claim_audit import RUNTIME_PATH, load_runtime
from test_runtime_integrity import make_complete_workspace, write_json


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class AttestationRedTeamV3Tests(unittest.TestCase):
    def test_offline_forged_runtime_receipt_requires_unforgeable_provenance(self):
        """A self-consistent, caller-authored receipt must not impersonate runtime fetch."""

        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _, _ = make_complete_workspace(
                runtime, Path(tmp), attest=False
            )

            checked = run_cli("check", "--workspace", str(workspace))
            payload = json.loads(checked.stdout)
            codes = {error["code"] for error in payload.get("errors", [])}

            self.assertTrue(
                checked.returncode != 0
                and "RECEIPT_PROVENANCE_UNATTESTED" in codes,
                "a fully offline, caller-authored runtime_fetch receipt passed the CLI gate; "
                f"returncode={checked.returncode}, verdict={payload.get('verdict')}, "
                f"codes={sorted(codes)}",
            )

    def test_replay_rejects_report_rehash_that_is_not_canonical_runtime_output(self):
        """Rehashing a tampered report in state.json must not make replay pass."""

        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _, _ = make_complete_workspace(runtime, Path(tmp))
            finished = run_cli("finish", "--workspace", str(workspace))
            self.assertEqual(finished.returncode, 0, finished.stderr)

            state_path = workspace / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            report_path = workspace / state["report"]
            forged_report = report_path.read_text(encoding="utf-8") + (
                "\n## Forged conclusion\n\nThis paragraph was not rendered by the runtime.\n"
            )
            report_path.write_text(forged_report, encoding="utf-8")
            state["report_sha256"] = hashlib.sha256(
                forged_report.encode("utf-8")
            ).hexdigest()
            write_json(state_path, state)

            replayed = run_cli("replay", "--workspace", str(workspace))
            payload = json.loads(replayed.stdout)
            codes = {error["code"] for error in payload.get("errors", [])}

            self.assertTrue(
                replayed.returncode != 0
                and "REPORT_CANONICAL_MISMATCH" in codes,
                "replay trusted a tampered report after the attacker synchronized "
                f"state.report_sha256; returncode={replayed.returncode}, "
                f"historical_integrity={payload.get('historical_integrity')}, "
                f"report_integrity={payload.get('report_integrity')}, "
                f"codes={sorted(codes)}",
            )


if __name__ == "__main__":
    unittest.main()
