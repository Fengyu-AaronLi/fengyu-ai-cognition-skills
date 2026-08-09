from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "tests"))

import test_round29_improvement_loop_red as round29  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Round40LoopAttestationRedTests(unittest.TestCase):
    def test_fully_forged_terminal_state_cannot_resume_as_stop(self) -> None:
        helper = round29.Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round40-forged-state-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            helper.start(paths)
            state_path = paths["state_dir"] / "loop-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["status"] = "completed"
            state["decision"] = "STOP"
            state["iterations"][0].update(
                {
                    "finding": None,
                    "red_test": None,
                    "gate_result": {
                        "path": ".ao-output/loop-run/missing-gate.json",
                        "sha256": "0" * 64,
                        "checks": {
                            key: True for key in round29.REQUIRED_GATE_CHECKS
                        },
                        "evidence": {
                            key: {} for key in round29.REQUIRED_GATE_CHECKS
                        },
                        "evidence_verified": True,
                        "valid": True,
                        "all_true": True,
                        "code": "GATE_VALID",
                    },
                    "decision": "STOP",
                }
            )
            state_path.write_text(
                json.dumps(state, indent=2) + "\n", encoding="utf-8"
            )

            result = helper.run_loop("resume", "--state-dir", paths["state_dir"])
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(
                "STATE_EVIDENCE_INVALID", helper.parsed(result)["error"]["code"]
            )

    def test_stop_is_invalid_if_bound_evidence_changes_after_commit(self) -> None:
        helper = round29.Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round40-tamper-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            started = helper.start(paths)
            gate_path, gate = helper.write_gate(paths, started)
            stopped = helper.advance(paths, gate_path)
            self.assertEqual(0, stopped.returncode, stopped.stdout + stopped.stderr)

            rollback_path = paths["repo"] / gate["evidence"]["rollback"]["path"]
            rollback_path.write_text(
                rollback_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            resumed = helper.run_loop(
                "resume", "--state-dir", paths["state_dir"]
            )
            self.assertNotEqual(0, resumed.returncode, resumed.stdout + resumed.stderr)
            self.assertEqual(
                "STATE_EVIDENCE_INVALID", helper.parsed(resumed)["error"]["code"]
            )

    def test_gate_file_itself_must_be_inside_the_candidate_repository(self) -> None:
        helper = round29.Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round40-external-gate-") as temp_dir:
            root = Path(temp_dir)
            paths = helper.make_candidate(root)
            started = helper.start(paths)
            gate_path, _ = helper.write_gate(paths, started)
            external_gate = root / "outside-gate.json"
            shutil.copy2(gate_path, external_gate)

            result = helper.advance(paths, external_gate)
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(
                "GATE_PATH_OUTSIDE_REPO", helper.parsed(result)["error"]["code"]
            )

    def test_one_generic_artifact_cannot_be_laundered_across_nine_checks(self) -> None:
        helper = round29.Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round40-artifact-reuse-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            started = helper.start(paths)
            gate_path, gate = helper.write_gate(paths, started)
            generic_relative = str(paths["red_test"].relative_to(paths["repo"]))
            generic_sha = sha256(paths["red_test"])
            for key, reference in gate["evidence"].items():
                evidence_path = paths["repo"] / reference["path"]
                document = json.loads(evidence_path.read_text(encoding="utf-8"))
                document["artifacts"] = [
                    {
                        "role": document["artifacts"][0]["role"],
                        "path": generic_relative,
                        "sha256": generic_sha,
                    }
                ]
                evidence_path.write_text(
                    json.dumps(document, indent=2) + "\n", encoding="utf-8"
                )
                reference["sha256"] = sha256(evidence_path)
            gate_path.write_text(
                json.dumps(gate, indent=2) + "\n", encoding="utf-8"
            )

            result = helper.advance(paths, gate_path)
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(
                "GATE_ARTIFACT_REUSE", helper.parsed(result)["error"]["code"]
            )


if __name__ == "__main__":
    unittest.main()
