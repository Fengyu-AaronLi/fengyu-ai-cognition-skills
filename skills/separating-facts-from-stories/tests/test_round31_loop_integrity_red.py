from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[1]
WORKFLOW = REPO_ROOT / "workflows" / "separating-facts-loop.yaml"
sys.path.insert(0, str(SKILL_DIR / "tests"))

import test_round29_improvement_loop_red as round29  # noqa: E402


class Round31LoopIntegrityRedTests(unittest.TestCase):
    """Regression tests for the executable improvement-loop evidence chain."""

    maxDiff = None

    def setUp(self) -> None:
        self.helper = round29.Round29ImprovementLoopRedTests()

    @staticmethod
    def _parsed(result: Any) -> dict[str, Any]:
        if not result.stdout.strip():
            raise AssertionError(
                f"controller returned no JSON; stderr was: {result.stderr}"
            )
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise AssertionError(f"controller output is not an object: {value!r}")
        return value

    def _start_without_workflow_source(
        self, paths: dict[str, Path]
    ) -> dict[str, Any]:
        result = self.helper.run_loop(
            "start",
            "--repo-root",
            paths["repo"],
            "--workflow",
            "workflows/separating-facts-loop.yaml",
            "--state-dir",
            ".ao-output/loop-run",
            "--source-file",
            "skills/separating-facts-from-stories/SKILL.md",
            "--source-file",
            "skills/separating-facts-from-stories/tests/test_probe.py",
            "--allow-write",
            "skills/separating-facts-from-stories",
            "--allow-write",
            "workflows",
            "--allow-write",
            ".ao-output",
            "--max-rounds",
            3,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return self._parsed(result)

    def test_workflow_is_automatically_frozen_and_drift_invalidates_stop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round31-workflow-") as temp_dir:
            paths = self.helper.make_candidate(Path(temp_dir))
            started = self._start_without_workflow_source(paths)

            self.assertIn(
                "workflows/separating-facts-loop.yaml",
                started["source_files"],
                "the declared workflow must be frozen even when callers omit it",
            )
            paths["workflow"].write_text(
                paths["workflow"].read_text(encoding="utf-8")
                + "# changed after freeze\n",
                encoding="utf-8",
            )
            gate_path, _ = self.helper.write_gate(paths, started)

            result = self.helper.advance(paths, gate_path)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            state = self._parsed(result)
            self.assertEqual("LOOP", state["decision"])
            self.assertEqual(
                "SOURCE_DRIFT_INVALIDATED_GATE",
                state["iterations"][0]["gate_result"]["code"],
            )
            finding = state["iterations"][0]["finding"]
            self.assertEqual(
                state["source_snapshot"]["sha256"], finding["actual"]
            )
            self.assertEqual(
                started["source_snapshot"]["sha256"], finding["expected"]
            )

    def test_resume_finishes_archive_when_committed_marker_was_not_renamed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round31-committed-") as temp_dir:
            paths = self.helper.make_candidate(Path(temp_dir))
            started = self.helper.start(paths)
            gate_path, _ = self.helper.write_gate(paths, started)
            advanced = self.helper.advance(paths, gate_path)
            self.assertEqual(0, advanced.returncode, advanced.stdout + advanced.stderr)

            transaction_files = list(
                (paths["state_dir"] / "transactions").glob("*.json")
            )
            self.assertEqual(1, len(transaction_files))
            pending = paths["state_dir"] / "pending-transition.json"
            transaction_files[0].replace(pending)
            intent = json.loads(pending.read_text(encoding="utf-8"))
            self.assertEqual("committed", intent["status"])

            resumed = self.helper.run_loop(
                "resume", "--state-dir", paths["state_dir"]
            )
            self.assertEqual(0, resumed.returncode, resumed.stdout + resumed.stderr)
            state = self._parsed(resumed)
            self.assertEqual("STOP", state["decision"])
            self.assertFalse(pending.exists())
            archive = (
                paths["state_dir"]
                / "transactions"
                / f"{intent['transaction_id']}.json"
            )
            self.assertTrue(archive.is_file())

    def test_resume_invalidates_a_prepared_stop_after_source_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round31-resume-drift-") as temp_dir:
            paths = self.helper.make_candidate(Path(temp_dir))
            started = self.helper.start(paths)
            gate_path, _ = self.helper.write_gate(paths, started)

            crashed = self.helper.advance(
                paths,
                gate_path,
                env={"SFFS_IMPROVEMENT_LOOP_FAILPOINT": "after_prepare"},
            )
            self.assertEqual(70, crashed.returncode, crashed.stdout + crashed.stderr)
            self.assertEqual(
                "SIMULATED_CRASH", self._parsed(crashed)["error"]["code"]
            )
            paths["skill_file"].write_text(
                paths["skill_file"].read_text(encoding="utf-8")
                + "\nChanged after the prepared STOP.\n",
                encoding="utf-8",
            )

            resumed = self.helper.run_loop(
                "resume", "--state-dir", paths["state_dir"]
            )
            self.assertEqual(0, resumed.returncode, resumed.stdout + resumed.stderr)
            state = self._parsed(resumed)
            self.assertEqual("LOOP", state["decision"])
            self.assertEqual("active", state["status"])
            self.assertEqual(2, state["current_round"])
            self.assertEqual(
                "SOURCE_DRIFT_INVALIDATED_GATE",
                state["iterations"][0]["gate_result"]["code"],
            )
            self.assertNotEqual(
                started["source_snapshot"]["sha256"],
                state["source_snapshot"]["sha256"],
            )
            aborted = list(
                (paths["state_dir"] / "transactions").glob("*-aborted.json")
            )
            self.assertEqual(1, len(aborted))

    def test_same_schema_malformed_state_fails_with_stable_json_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round31-state-") as temp_dir:
            paths = self.helper.make_candidate(Path(temp_dir))
            started = self.helper.start(paths)
            gate_path, _ = self.helper.write_gate(paths, started)
            state_path = paths["state_dir"] / "loop-state.json"
            malformed = json.loads(state_path.read_text(encoding="utf-8"))
            malformed.pop("source_files")
            state_path.write_text(
                json.dumps(malformed, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            result = self.helper.advance(paths, gate_path)
            self.assertNotEqual(0, result.returncode)
            payload = self._parsed(result)
            self.assertEqual("STATE_INVALID", payload["error"]["code"])
            self.assertNotIn("Traceback", result.stderr)

    def test_argument_errors_use_the_same_structured_json_channel(self) -> None:
        result = self.helper.run_loop("start")
        self.assertNotEqual(0, result.returncode)
        payload = self._parsed(result)
        self.assertEqual("ARGUMENT_ERROR", payload["error"]["code"])
        self.assertNotIn("usage:", result.stderr)

    def test_declared_clean_target_is_consumed_by_the_workflow(self) -> None:
        workflow_text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("{{clean_target_root}}", workflow_text)


if __name__ == "__main__":
    unittest.main()
