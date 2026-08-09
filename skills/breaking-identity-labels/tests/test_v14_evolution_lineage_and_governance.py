#!/usr/bin/env python3
"""V14 red contracts for governance-bound freezes and iteration lineage.

These tests deliberately exercise the public CLI.  A release freeze is not
honest if changing the controller, builders, evaluator, or executable workflow
leaves the frozen candidate valid.  Likewise, a new iteration is not a loop if
it can be spawned from unfinished work or overwrite its predecessor.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts" / "run_evolution.py"
DEMO_FILES = (
    ".case.lock",
    "analysis.json",
    "case.json",
    "demo-input.txt",
    "events.head.json",
    "events.jsonl",
    "report.md",
    "run-manifest.json",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def result_payload(result: subprocess.CompletedProcess[str]) -> dict:
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


class V14Fixture:
    """Small, fully local repository accepted by the controller contracts."""

    def __init__(self, root: Path) -> None:
        self.root = root
        for relative in (
            "scripts",
            "schemas",
            "tests",
            "workflows",
            "evals/findings",
            "evals/runs",
            "examples/real-run",
        ):
            (root / relative).mkdir(parents=True, exist_ok=True)

        files = {
            "scripts/identity_label_case.py": "print('runtime')\n",
            "scripts/run_evolution.py": "# governance fixture: controller\n",
            "scripts/build_demo.py": "# governance fixture: demo builder\n",
            "evals/validate.py": "# governance fixture: evaluator\n",
            "scripts/worker_success.py": "print('OK')\n",
            "scripts/worker_fail.py": "print('not green')\nraise SystemExit(1)\n",
            "tests/test_v13_preserved.py": "# frozen predecessor contract\n",
            "evals/findings/v14.md": "B-V14 remains open for the next iteration.\n",
        }
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        (root / "scripts" / "build_package.py").write_text(
            "import json\nprint(json.dumps({'status': 'built', 'tree_sha256': 'f' * 64}))\n",
            encoding="utf-8",
        )
        write_json(root / "schemas" / "case.schema.json", {"type": "object"})
        write_json(root / "schemas" / "release-gate.schema.json", {"type": "object"})
        for name in DEMO_FILES:
            (root / "examples" / "real-run" / name).write_text(
                f"fixture:{name}\n", encoding="utf-8"
            )

        test_path = root / "tests" / "test_v13_preserved.py"
        self.manifest = root / "evals" / "test-generation-manifest.json"
        write_json(
            self.manifest,
            {
                "schema_version": "1.0",
                "generation_rules": [
                    {
                        "generation": "v13",
                        "minimum": 1,
                        "pattern": "tests/test_v13_*.py",
                    }
                ],
                "files": [
                    {
                        "generation": "v13",
                        "path": "tests/test_v13_preserved.py",
                        "sha256": digest(test_path),
                    }
                ],
            },
        )

        self.workflow = root / "workflows" / "v14-executable.json"
        write_json(
            self.workflow,
            {
                "schema_version": "1.0",
                "workflow_id": "identity-v14-executable",
                "description": "One real command, suitable for controller preflight and execution.",
                "steps": [
                    {
                        "id": "green",
                        "kind": "command",
                        "depends_on": [],
                        "argv": ["{python}", "{root}/scripts/worker_success.py"],
                        "expected": "exit_zero",
                    }
                ],
            },
        )
        self.waiting_workflow = root / "workflows" / "v14-waiting.json"
        write_json(
            self.waiting_workflow,
            {
                "schema_version": "1.0",
                "workflow_id": "identity-v14-waiting",
                "steps": [
                    {
                        "id": "human_review",
                        "kind": "external",
                        "depends_on": [],
                    }
                ],
            },
        )
        self.failed_workflow = root / "workflows" / "v14-failed.json"
        write_json(
            self.failed_workflow,
            {
                "schema_version": "1.0",
                "workflow_id": "identity-v14-failed",
                "steps": [
                    {
                        "id": "green",
                        "kind": "command",
                        "depends_on": [],
                        "argv": ["{python}", "{root}/scripts/worker_fail.py"],
                        "expected": "exit_zero",
                    }
                ],
            },
        )
        self.release_state = root / "evals" / "release-gate.json"

    def controller(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CONTROLLER),
                *args,
                "--root",
                str(self.root),
                "--state",
                str(self.release_state),
                "--test-manifest",
                str(self.manifest),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def freeze(self) -> subprocess.CompletedProcess[str]:
        completed_run = self.root / "evals" / "runs" / "release-freeze"
        started = self.start(
            self.workflow,
            completed_run,
            "release-freeze-v14",
            "candidate-freeze-v14",
        )
        if started.returncode != 0:
            return started
        return self.controller(
            "freeze",
            "--candidate-id",
            "candidate-freeze-v14",
            "--workflow",
            str(self.workflow),
            "--completed-run-dir",
            str(completed_run),
        )

    def start(
        self,
        workflow: Path,
        run_dir: Path,
        run_id: str,
        candidate_id: str,
    ) -> subprocess.CompletedProcess[str]:
        return self.controller(
            "run",
            "--workflow",
            str(workflow),
            "--run-dir",
            str(run_dir),
            "--run-id",
            run_id,
            "--candidate-id",
            candidate_id,
        )

    def next_iteration(
        self,
        previous: Path,
        target: Path,
        *,
        run_id: str = "r2",
        candidate_id: str = "candidate-r2",
    ) -> subprocess.CompletedProcess[str]:
        return self.controller(
            "next-iteration",
            "--previous-run-dir",
            str(previous),
            "--run-dir",
            str(target),
            "--run-id",
            run_id,
            "--candidate-id",
            candidate_id,
            "--carry-over-blocker",
            "B-V14:P1:evals/findings/v14.md",
        )


class GovernanceBoundFreezeTests(unittest.TestCase):
    def make_fixture(self) -> tuple[tempfile.TemporaryDirectory[str], V14Fixture]:
        temporary = tempfile.TemporaryDirectory(prefix="identity-v14-governance-")
        return temporary, V14Fixture(Path(temporary.name))

    def test_freeze_snapshot_names_governance_tree_and_executable_workflow(self) -> None:
        temporary, fixture = self.make_fixture()
        self.addCleanup(temporary.cleanup)

        result = fixture.freeze()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        state = json.loads(fixture.release_state.read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "scripts/run_evolution.py",
                "scripts/build_package.py",
                "scripts/build_demo.py",
                "evals/validate.py",
            },
            set(state["governance_files"]),
        )
        self.assertEqual("workflows/v14-executable.json", state["workflow_path"])
        self.assertEqual(digest(fixture.workflow), state["artifacts"]["workflow_sha256"])
        self.assertRegex(state["artifacts"]["governance_tree_sha256"], r"^[0-9a-f]{64}$")

    def test_each_governance_or_workflow_drift_invalidates_the_frozen_gate(self) -> None:
        targets = (
            ("scripts/run_evolution.py", "governance_tree_sha256_drift"),
            ("scripts/build_package.py", "governance_tree_sha256_drift"),
            ("scripts/build_demo.py", "governance_tree_sha256_drift"),
            ("evals/validate.py", "governance_tree_sha256_drift"),
            ("workflows/v14-executable.json", "workflow_sha256_drift"),
        )
        for relative, expected_code in targets:
            with self.subTest(relative=relative):
                temporary, fixture = self.make_fixture()
                try:
                    frozen = fixture.freeze()
                    self.assertEqual(0, frozen.returncode, frozen.stdout + frozen.stderr)
                    target = fixture.root / relative
                    target.write_text(
                        target.read_text(encoding="utf-8") + "\n",
                        encoding="utf-8",
                    )
                    checked = fixture.controller("check", "--allow-blocked")
                    payload = result_payload(checked)
                    self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
                    self.assertTrue(payload["valid"])
                    self.assertEqual("invalid_run", payload["effective_decision"])
                    self.assertFalse(payload["release_eligible"])
                    self.assertIn(expected_code, payload["invalidations"])
                finally:
                    temporary.cleanup()

    def test_freeze_rejects_a_workflow_that_is_not_controller_executable(self) -> None:
        temporary, fixture = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        write_json(
            fixture.workflow,
            {
                "schema_version": "1.0",
                "workflow_id": "identity-v14-document-only",
                "description": "Narrative metadata is not an executable step graph.",
                "steps": [],
            },
        )

        result = fixture.freeze()
        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn(
            "evolution_workflow_steps_invalid",
            set(result_payload(result).get("errors", [])),
        )
        self.assertFalse(fixture.release_state.exists())


class NextIterationLineageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v14-lineage-")
        self.fixture = V14Fixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_next_iteration_from_complete_run_preserves_lineage_and_old_evidence(self) -> None:
        previous = self.fixture.root / "evals" / "runs" / "r1"
        started = self.fixture.start(
            self.fixture.workflow, previous, "r1", "candidate-r1"
        )
        self.assertEqual(0, started.returncode, started.stdout + started.stderr)
        old_events = (previous / "events.jsonl").read_bytes()
        old_receipt = (previous / "receipts" / "green.json").read_bytes()
        old_state = (previous / "run-state.json").read_bytes()

        target = self.fixture.root / "evals" / "runs" / "r2"
        advanced = self.fixture.next_iteration(previous, target)
        self.assertEqual(0, advanced.returncode, advanced.stdout + advanced.stderr)
        state = json.loads((target / "run-state.json").read_text(encoding="utf-8"))
        self.assertEqual("r1", state["predecessor_run_id"])
        self.assertEqual("candidate-r1", state["predecessor_candidate_id"])
        self.assertEqual("candidate-r2", state["candidate_id"])
        self.assertNotEqual(state["candidate_id"], state["predecessor_candidate_id"])
        self.assertEqual(
            [
                {
                    "id": "B-V14",
                    "severity": "P1",
                    "evidence": "evals/findings/v14.md",
                }
            ],
            state["carry_over_blockers"],
        )
        self.assertEqual(old_events, (previous / "events.jsonl").read_bytes())
        self.assertEqual(old_receipt, (previous / "receipts" / "green.json").read_bytes())
        self.assertEqual(old_state, (previous / "run-state.json").read_bytes())
        self.assertTrue((target / "receipts" / "green.json").is_file())

    def test_next_iteration_refuses_candidate_reuse_and_predecessor_overwrite(self) -> None:
        previous = self.fixture.root / "evals" / "runs" / "r1"
        started = self.fixture.start(
            self.fixture.workflow, previous, "r1", "candidate-r1"
        )
        self.assertEqual(0, started.returncode, started.stdout + started.stderr)
        old_events = (previous / "events.jsonl").read_bytes()
        old_receipt = (previous / "receipts" / "green.json").read_bytes()

        reused = self.fixture.next_iteration(
            previous,
            self.fixture.root / "evals" / "runs" / "candidate-reused",
            candidate_id="candidate-r1",
        )
        self.assertEqual(3, reused.returncode, reused.stdout + reused.stderr)
        self.assertIn(
            "evolution_candidate_id_reused",
            set(result_payload(reused).get("errors", [])),
        )

        overwritten = self.fixture.next_iteration(
            previous,
            previous,
            run_id="r2-overwrite",
            candidate_id="candidate-r2-overwrite",
        )
        self.assertEqual(3, overwritten.returncode, overwritten.stdout + overwritten.stderr)
        self.assertEqual(old_events, (previous / "events.jsonl").read_bytes())
        self.assertEqual(old_receipt, (previous / "receipts" / "green.json").read_bytes())

    def test_next_iteration_cannot_jump_from_waiting_run(self) -> None:
        predecessors = (
            (self.fixture.waiting_workflow, "waiting", "candidate-waiting", 2),
        )
        for index, (workflow, run_id, candidate_id, expected_start) in enumerate(
            predecessors, start=1
        ):
            with self.subTest(run_id=run_id):
                previous = self.fixture.root / "evals" / "runs" / run_id
                started = self.fixture.start(workflow, previous, run_id, candidate_id)
                self.assertEqual(
                    expected_start,
                    started.returncode,
                    started.stdout + started.stderr,
                )
                before_events = (previous / "events.jsonl").read_bytes()
                before_state = (previous / "run-state.json").read_bytes()
                target = self.fixture.root / "evals" / "runs" / f"illegal-next-{index}"
                advanced = self.fixture.next_iteration(
                    previous,
                    target,
                    run_id=f"illegal-next-{index}",
                    candidate_id=f"candidate-illegal-next-{index}",
                )
                self.assertEqual(3, advanced.returncode, advanced.stdout + advanced.stderr)
                self.assertIn(
                    "evolution_predecessor_not_terminal",
                    set(result_payload(advanced).get("errors", [])),
                )
                self.assertFalse(target.exists())
                self.assertEqual(before_events, (previous / "events.jsonl").read_bytes())
                self.assertEqual(before_state, (previous / "run-state.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
