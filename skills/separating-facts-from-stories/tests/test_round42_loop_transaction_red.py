from __future__ import annotations

import fcntl
import hashlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "tests"))

import test_round29_improvement_loop_red as round29  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Round42LoopTransactionRedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.helper = round29.Round29ImprovementLoopRedTests()

    def test_advance_obeys_the_controller_exclusive_lock(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round42-lock-") as temp_dir:
            paths = self.helper.make_candidate(Path(temp_dir))
            started = self.helper.start(paths)
            gate_path, _ = self.helper.write_gate(paths, started)
            lock_path = paths["state_dir"].with_name(
                f".{paths['state_dir'].name}.controller.lock"
            )
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a+", encoding="utf-8") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(round29.LOOP_SCRIPT),
                        "advance",
                        "--state-dir",
                        str(paths["state_dir"]),
                        "--gate",
                        str(gate_path),
                    ],
                    cwd=round29.REPO_ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                try:
                    time.sleep(0.4)
                    self.assertIsNone(
                        process.poll(),
                        "advance ignored the lock and raced another state transition",
                    )
                finally:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
                stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(0, process.returncode, stdout + stderr)

    def test_prepared_stop_is_not_published_after_evidence_tamper(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round42-prepared-") as temp_dir:
            paths = self.helper.make_candidate(Path(temp_dir))
            started = self.helper.start(paths)
            gate_path, gate = self.helper.write_gate(paths, started)
            crashed = self.helper.advance(
                paths,
                gate_path,
                env={"SFFS_IMPROVEMENT_LOOP_FAILPOINT": "after_prepare"},
            )
            self.assertEqual(70, crashed.returncode, crashed.stdout + crashed.stderr)
            rollback = paths["repo"] / gate["evidence"]["rollback"]["path"]
            rollback.write_text(
                rollback.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            )

            resumed = self.helper.run_loop(
                "resume", "--state-dir", paths["state_dir"]
            )
            self.assertNotEqual(0, resumed.returncode, resumed.stdout + resumed.stderr)
            self.assertEqual(
                "STATE_EVIDENCE_INVALID",
                self.helper.parsed(resumed)["error"]["code"],
            )
            live = json.loads(
                (paths["state_dir"] / "loop-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual("active", live["status"])
            self.assertTrue(
                list((paths["state_dir"] / "transactions").glob("*-aborted.json"))
            )

    def test_budget_exhausted_source_drift_remains_reloadable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round42-budget-") as temp_dir:
            paths = self.helper.make_candidate(Path(temp_dir))
            started = self.helper.start(paths, max_rounds=1)
            gate_path, _ = self.helper.write_gate(paths, started)
            paths["skill_file"].write_text(
                paths["skill_file"].read_text(encoding="utf-8") + "\nchanged\n",
                encoding="utf-8",
            )
            exhausted = self.helper.advance(paths, gate_path)
            self.assertEqual(0, exhausted.returncode, exhausted.stdout + exhausted.stderr)
            blocked = self.helper.parsed(exhausted)
            self.assertEqual("BUDGET_EXHAUSTED", blocked["decision"])
            self.assertIn("observed_source_snapshot", blocked)

            resumed = self.helper.run_loop(
                "resume", "--state-dir", paths["state_dir"]
            )
            self.assertEqual(0, resumed.returncode, resumed.stdout + resumed.stderr)
            self.assertEqual("blocked", self.helper.parsed(resumed)["status"])

    def test_material_workflow_policy_drift_requires_a_fresh_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round42-policy-") as temp_dir:
            paths = self.helper.make_candidate(Path(temp_dir))
            started = self.helper.start(paths)
            workflow = paths["workflow"].read_text(encoding="utf-8")
            paths["workflow"].write_text(
                workflow.replace("  max_rounds: 3\n", "  max_rounds: 1\n"),
                encoding="utf-8",
            )
            gate_path, _ = self.helper.write_gate(paths, started)
            result = self.helper.advance(paths, gate_path)
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(
                "WORKFLOW_POLICY_CHANGED",
                self.helper.parsed(result)["error"]["code"],
            )

    def test_red_test_must_be_frozen_and_historical_hash_is_rechecked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round42-redtest-") as temp_dir:
            paths = self.helper.make_candidate(Path(temp_dir))
            started = self.helper.start(paths)
            gate_path, _ = self.helper.write_gate(
                paths, started, overrides={"unit_tests": False}
            )
            finding_path, _ = self.helper.write_finding(paths)
            scratch = paths["repo"] / "scratch" / "not-frozen.py"
            scratch.parent.mkdir()
            scratch.write_text("assert True\n", encoding="utf-8")
            rejected = self.helper.run_loop(
                "advance",
                "--state-dir",
                paths["state_dir"],
                "--gate",
                gate_path,
                "--finding",
                finding_path,
                "--red-test",
                scratch,
            )
            self.assertNotEqual(0, rejected.returncode, rejected.stdout + rejected.stderr)
            self.assertEqual(
                "RED_TEST_NOT_FROZEN", self.helper.parsed(rejected)["error"]["code"]
            )

            accepted = self.helper.advance(paths, gate_path, finding=finding_path)
            self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)
            paths["red_test"].write_text(
                paths["red_test"].read_text(encoding="utf-8") + "\n# tampered\n",
                encoding="utf-8",
            )
            resumed = self.helper.run_loop(
                "resume", "--state-dir", paths["state_dir"]
            )
            self.assertNotEqual(0, resumed.returncode, resumed.stdout + resumed.stderr)
            self.assertEqual(
                "STATE_EVIDENCE_INVALID",
                self.helper.parsed(resumed)["error"]["code"],
            )

    def test_install_verify_and_rollback_must_bind_one_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round42-install-chain-") as temp_dir:
            paths = self.helper.make_candidate(Path(temp_dir))
            started = self.helper.start(paths)
            gate_path, gate = self.helper.write_gate(paths, started)
            replacements = {
                "verify_install": {"manifest_sha256": "4" * 64},
                "rollback": {
                    "installed_manifest_sha256": "5" * 64,
                    "restored_manifest_sha256": "5" * 64,
                },
            }
            for key, updates in replacements.items():
                reference = gate["evidence"][key]
                evidence_path = paths["repo"] / reference["path"]
                document = json.loads(evidence_path.read_text(encoding="utf-8"))
                document["proof"].update(updates)
                evidence_path.write_text(
                    json.dumps(document, indent=2) + "\n", encoding="utf-8"
                )
                reference["sha256"] = sha256(evidence_path)
            gate_path.write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")

            result = self.helper.advance(paths, gate_path)
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(
                "GATE_INSTALL_CHAIN_MISMATCH",
                self.helper.parsed(result)["error"]["code"],
            )


if __name__ == "__main__":
    unittest.main()
