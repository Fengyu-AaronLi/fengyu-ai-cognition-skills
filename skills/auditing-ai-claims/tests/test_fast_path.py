from __future__ import annotations

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


class FastPathWorkflowTests(unittest.TestCase):
    def test_start_initializes_and_scopes_in_one_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("A current price claim.", encoding="utf-8")
            workspace = root / "run"

            started = run_cli(
                "start",
                "--input",
                str(input_path),
                "--workspace",
                str(workspace),
                "--as-of",
                "2026-08-05",
                "--reason",
                "current product price",
                "--candidate",
                "A current price claim.",
            )

            self.assertEqual(started.returncode, 0, started.stderr)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            self.assertTrue(ledger["scope"]["triggered"])
            self.assertEqual(ledger["scope"]["reason"], "current product price")
            self.assertEqual(ledger["scope"]["unreviewed_claims"], ["A current price claim."])

    def test_add_claim_and_decide_need_no_intermediate_json_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text(
                "Model X is currently the cheapest text model.", encoding="utf-8"
            )
            workspace = root / "run"
            self.assertEqual(
                run_cli(
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--as-of",
                    "2026-08-05",
                    "--reason",
                    "current product price",
                    "--candidate",
                    "Model X is currently the cheapest text model.",
                ).returncode,
                0,
            )

            added = run_cli(
                "add-claim",
                "--workspace",
                str(workspace),
                "--claim-id",
                "C1",
                "--text",
                "Model X is currently the cheapest text model.",
                "--type",
                "quantitative_comparison",
                "--temporal",
                "high",
                "--as-of",
                "2026-08-05",
                "--criterion",
                "The current official price table lists every in-scope text model.",
                "--criterion",
                "Model X has the lowest non-cached input price in that comparison set.",
                "--failure-condition",
                "A cheaper in-scope model appears in the same current table.",
                "--next-step",
                "Open the official current price table.",
                "--covers",
                "Model X is currently the cheapest text model.",
            )
            self.assertEqual(added.returncode, 0, added.stderr)

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
                "current_unknown",
                "--confidence-reason",
                "No eligible current official receipt was obtained.",
                "--next-step",
                "Open and save the official current price table.",
                "--unknown",
                "Current comparison set and price remain unverified.",
                "--next-action",
                "Fetch the official current price table.",
            )
            self.assertEqual(decided.returncode, 0, decided.stderr)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            claim = ledger["claims"][0]
            self.assertEqual(claim["status"], "current_unknown")
            self.assertEqual(claim["temporal_sensitivity"], "high")
            self.assertEqual(len(claim["criteria"]["conditions"]), 2)

    def test_decide_requires_explicit_unknowns_and_global_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("The named paper exists.", encoding="utf-8")
            workspace = root / "run"
            self.assertEqual(
                run_cli(
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "named paper claim",
                    "--candidate",
                    "The named paper exists.",
                ).returncode,
                0,
            )
            self.assertEqual(
                run_cli(
                    "add-claim",
                    "--workspace",
                    str(workspace),
                    "--claim-id",
                    "C1",
                    "--text",
                    "The named paper exists.",
                    "--type",
                    "existence_identity",
                    "--temporal",
                    "low",
                    "--criterion",
                    "A publisher record matches the supplied identity fields.",
                    "--failure-condition",
                    "The supplied identity fields resolve to a different record.",
                    "--next-step",
                    "Open the publisher record.",
                    "--covers",
                    "The named paper exists.",
                ).returncode,
                0,
            )
            common = (
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
                "No eligible publisher receipt was obtained.",
                "--next-step",
                "Resolve the DOI at the publisher or registry.",
            )

            missing_unknown = run_cli(
                *common,
                "--next-action",
                "Resolve the DOI at a primary registry.",
            )
            self.assertNotEqual(missing_unknown.returncode, 0)
            self.assertIn("--unknown", missing_unknown.stderr)

            missing_next_action = run_cli(
                *common,
                "--unknown",
                "The paper identity remains unverified.",
            )
            self.assertNotEqual(missing_next_action.returncode, 0)
            self.assertIn("--next-action", missing_next_action.stderr)

    def test_link_auto_binds_an_exact_quote_selector(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text(
                "The framework is intended for voluntary use.", encoding="utf-8"
            )
            source_path = root / "source.html"
            source_path.write_text(
                "<html><body><p>The Framework is intended to be voluntary.</p></body></html>",
                encoding="utf-8",
            )
            workspace = root / "run"
            self.assertEqual(
                run_cli(
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "official framework claim",
                    "--candidate",
                    "The framework is intended for voluntary use.",
                ).returncode,
                0,
            )
            self.assertEqual(
                run_cli(
                    "add-claim",
                    "--workspace",
                    str(workspace),
                    "--claim-id",
                    "C1",
                    "--text",
                    "The framework is intended for voluntary use.",
                    "--type",
                    "law_policy",
                    "--temporal",
                    "low",
                    "--criterion",
                    "The original framework states that use is voluntary.",
                    "--failure-condition",
                    "The original framework states that use is mandatory.",
                    "--next-step",
                    "Open the original framework.",
                    "--covers",
                    "The framework is intended for voluntary use.",
                ).returncode,
                0,
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
                    "https://example.com/framework",
                    "--final-url",
                    "https://example.com/framework",
                    "--http-status",
                    "200",
                    "--content-type",
                    "text/html; charset=utf-8",
                    "--tier",
                    "A1",
                    "--role",
                    "original_record",
                    "--published",
                    "2023-01-01",
                    "--origin-id",
                    "framework:v1",
                    "--acquisition-type",
                    "browser_export",
            )
            self.assertNotEqual(captured.returncode, 0)

            linked = run_cli(
                "link",
                "--workspace",
                str(workspace),
                "--claim-id",
                "C1",
                "--source-id",
                "S1",
                "--support",
                "direct",
                "--support-scope",
                "the stated voluntary-use intent of this framework version",
                "--exact",
                "The Framework is intended to be voluntary.",
                "--inference-span",
                "0",
            )

            self.assertEqual(linked.returncode, 0, linked.stderr)
            evidence = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))["claims"][0]["evidence"][0]
            self.assertEqual(evidence["excerpt"], "The Framework is intended to be voluntary.")
            self.assertEqual(len(evidence["selector"]["quote_sha256"]), 64)
            self.assertEqual(evidence["locator"], f"chars {evidence['selector']['start']}:{evidence['selector']['end']}")

    def test_finish_runs_gate_then_renders_or_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("The named paper exists.", encoding="utf-8")
            workspace = root / "run"
            self.assertEqual(
                run_cli(
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "named paper claim",
                    "--candidate",
                    "The named paper exists.",
                ).returncode,
                0,
            )
            self.assertEqual(
                run_cli(
                    "add-claim",
                    "--workspace",
                    str(workspace),
                    "--claim-id",
                    "C1",
                    "--text",
                    "The named paper exists.",
                    "--type",
                    "existence_identity",
                    "--temporal",
                    "low",
                    "--criterion",
                    "A publisher record matches the supplied identity fields.",
                    "--failure-condition",
                    "The supplied identity fields resolve to a different record.",
                    "--next-step",
                    "Open the publisher record.",
                    "--covers",
                    "The named paper exists.",
                ).returncode,
                0,
            )
            self.assertEqual(
                run_cli(
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
                    "No eligible publisher receipt was obtained.",
                    "--next-step",
                    "Resolve the DOI at the publisher or registry.",
                    "--unknown",
                    "The paper identity remains unverified.",
                    "--next-action",
                    "Resolve the DOI at a primary registry.",
                ).returncode,
                0,
            )
            counterchecked = record_countercheck_cli(workspace, root)
            self.assertEqual(counterchecked.returncode, 0, counterchecked.stderr)
            summarized = run_cli(
                "summarize",
                "--workspace",
                str(workspace),
                "--unknown",
                "The paper identity remains unverified.",
                "--next-action",
                "Resolve the DOI at a primary registry.",
            )
            self.assertEqual(summarized.returncode, 0, summarized.stderr)

            finished = run_cli("finish", "--workspace", str(workspace))
            self.assertEqual(finished.returncode, 0, finished.stderr)
            self.assertTrue((workspace / "gate.json").is_file())
            self.assertTrue((workspace / "report.md").is_file())
            self.assertEqual(
                json.loads((workspace / "gate.json").read_text(encoding="utf-8"))["verdict"],
                "PASS",
            )

            ledger_path = workspace / "ledger.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["scope"]["unreviewed_claims"] = ["another material claim"]
            ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            blocked = run_cli("finish", "--workspace", str(workspace))
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("UNREVIEWED_CLAIMS_BLOCK_COMPLETION", blocked.stdout)

    def test_finish_refuses_a_claim_that_skipped_decide(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "answer.txt"
            input_path.write_text("The named paper exists.", encoding="utf-8")
            workspace = root / "run"
            self.assertEqual(
                run_cli(
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--reason",
                    "named paper claim",
                    "--candidate",
                    "The named paper exists.",
                ).returncode,
                0,
            )
            self.assertEqual(
                run_cli(
                    "add-claim",
                    "--workspace",
                    str(workspace),
                    "--claim-id",
                    "C1",
                    "--text",
                    "The named paper exists.",
                    "--type",
                    "existence_identity",
                    "--temporal",
                    "low",
                    "--criterion",
                    "A publisher record matches the supplied identity fields.",
                    "--failure-condition",
                    "The supplied identity fields resolve to a different record.",
                    "--next-step",
                    "Open the publisher record.",
                    "--covers",
                    "The named paper exists.",
                ).returncode,
                0,
            )

            finished = run_cli("finish", "--workspace", str(workspace))

            self.assertNotEqual(finished.returncode, 0)
            self.assertIn("CLAIM_ASSESSMENT_REQUIRED", finished.stdout)
            self.assertFalse((workspace / "report.md").exists())


if __name__ == "__main__":
    unittest.main()
