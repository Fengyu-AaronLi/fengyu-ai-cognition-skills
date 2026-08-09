#!/usr/bin/env python3
"""V48 contracts: one run writer and an honest command execution boundary."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from test_v14_evolution_lineage_and_governance import (
    CONTROLLER,
    V14Fixture,
    digest,
    result_payload,
    write_json,
)


class EvolutionLockAndExecutionBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v48-lock-")
        self.fixture = V14Fixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def argv(self, *args: str) -> list[str]:
        return [
            sys.executable,
            str(CONTROLLER),
            *args,
            "--root",
            str(self.fixture.root),
            "--state",
            str(self.fixture.release_state),
            "--test-manifest",
            str(self.fixture.manifest),
        ]

    def controller(self, *args: str, env: dict[str, str] | None = None):
        return subprocess.run(
            self.argv(*args),
            cwd=CONTROLLER.parent.parent,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    def write_workflow(self, name: str, steps: list[dict]) -> Path:
        path = self.fixture.root / "workflows" / f"{name}.json"
        write_json(
            path,
            {
                "schema_version": "1.0",
                "workflow_id": name,
                "steps": steps,
            },
        )
        return path

    def external_receipt(self, run_id: str, step_id: str, name: str) -> Path:
        evidence = self.fixture.root / "evals" / "findings" / f"{name}.md"
        evidence.write_text("External gate completed.\n", encoding="utf-8")
        receipt = self.fixture.root / "evals" / f"{name}.json"
        write_json(
            receipt,
            {
                "schema_version": "1.0",
                "run_id": run_id,
                "step_id": step_id,
                "status": "completed",
                "summary": "The preregistered external action completed.",
                "evidence": [
                    {
                        "path": evidence.relative_to(self.fixture.root).as_posix(),
                        "sha256": digest(evidence),
                    }
                ],
            },
        )
        return receipt

    def hold_lock(self, run_dir: Path):
        lock_path = run_dir.parent / f".{run_dir.name}.evolution.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+b")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle

    def test_parent_environment_secret_is_not_inherited_by_workflow_command(self) -> None:
        worker = self.fixture.root / "scripts" / "print_parent_secret.py"
        worker.write_text(
            "import os\nprint(os.environ.get('IDENTITY_V48_PARENT_SECRET', 'ABSENT'))\n",
            encoding="utf-8",
        )
        workflow = self.write_workflow(
            "identity-v48-env",
            [
                {
                    "id": "env_probe",
                    "kind": "command",
                    "depends_on": [],
                    "argv": ["{python}", "{root}/scripts/print_parent_secret.py"],
                    "expected": "exit_zero",
                }
            ],
        )
        run_dir = self.fixture.root / "evals" / "runs" / "v48-env"
        environment = dict(os.environ)
        environment["IDENTITY_V48_PARENT_SECRET"] = "must-not-leak"

        result = self.controller(
            "run",
            "--workflow",
            str(workflow),
            "--run-dir",
            str(run_dir),
            "--run-id",
            "v48-env",
            "--candidate-id",
            "candidate-v48-env",
            env=environment,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        receipt = json.loads((run_dir / "receipts" / "env_probe.json").read_text(encoding="utf-8"))
        stdout = (self.fixture.root / receipt["stdout_path"]).read_text(encoding="utf-8")
        self.assertNotIn("must-not-leak", stdout)
        self.assertEqual({"PYTHONHASHSEED": "0"}, receipt["input_snapshot"]["environment"])

    def test_receipt_binds_script_hash_from_before_execution(self) -> None:
        worker = self.fixture.root / "scripts" / "self_mutating_worker.py"
        worker.write_text(
            "from pathlib import Path\n"
            "path = Path(__file__)\n"
            "print('OK')\n"
            "path.write_text(\"print('mutated')\\n\", encoding='utf-8')\n",
            encoding="utf-8",
        )
        before = digest(worker)
        workflow = self.write_workflow(
            "identity-v48-prehash",
            [
                {
                    "id": "mutate",
                    "kind": "command",
                    "depends_on": [],
                    "argv": ["{python}", "{root}/scripts/self_mutating_worker.py"],
                    "expected": "exit_zero",
                }
            ],
        )
        run_dir = self.fixture.root / "evals" / "runs" / "v48-prehash"

        result = self.controller(
            "run",
            "--workflow",
            str(workflow),
            "--run-dir",
            str(run_dir),
            "--run-id",
            "v48-prehash",
            "--candidate-id",
            "candidate-v48-prehash",
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        receipt = json.loads((run_dir / "receipts" / "mutate.json").read_text(encoding="utf-8"))
        self.assertEqual(before, receipt["script_sha256"])
        status = self.controller("status", "--run-dir", str(run_dir))
        self.assertEqual(3, status.returncode, status.stdout + status.stderr)
        self.assertIn(
            "evolution_command_script_hash_mismatch",
            set(result_payload(status).get("errors", [])),
        )

    def test_held_run_lock_rejects_initial_run_without_creating_run_directory(self) -> None:
        run_dir = self.fixture.root / "evals" / "runs" / "v48-held-create"
        lock = self.hold_lock(run_dir)
        self.addCleanup(lock.close)

        result = self.controller(
            "run",
            "--workflow",
            str(self.fixture.workflow),
            "--run-dir",
            str(run_dir),
            "--run-id",
            "v48-held-create",
            "--candidate-id",
            "candidate-v48-held-create",
        )

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("evolution_run_locked", set(result_payload(result).get("errors", [])))
        self.assertFalse(run_dir.exists())

    def test_held_run_lock_rejects_external_completion_with_zero_state_writes(self) -> None:
        run_dir = self.fixture.root / "evals" / "runs" / "v48-external"
        started = self.controller(
            "run",
            "--workflow",
            str(self.fixture.waiting_workflow),
            "--run-dir",
            str(run_dir),
            "--run-id",
            "v48-external",
            "--candidate-id",
            "candidate-v48-external",
        )
        self.assertEqual(2, started.returncode, started.stdout + started.stderr)
        receipt = self.external_receipt("v48-external", "human_review", "v48-external")
        before = {
            path.relative_to(run_dir).as_posix(): path.read_bytes()
            for path in run_dir.rglob("*")
            if path.is_file()
        }
        lock = self.hold_lock(run_dir)
        self.addCleanup(lock.close)

        completed = self.controller(
            "complete-external",
            "--run-dir",
            str(run_dir),
            "--step-id",
            "human_review",
            "--receipt",
            str(receipt),
        )

        after = {
            path.relative_to(run_dir).as_posix(): path.read_bytes()
            for path in run_dir.rglob("*")
            if path.is_file()
        }
        self.assertEqual(3, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("evolution_run_locked", set(result_payload(completed).get("errors", [])))
        self.assertEqual(before, after)

    def test_two_concurrent_resumes_execute_pending_command_once(self) -> None:
        worker = self.fixture.root / "scripts" / "slow_worker.py"
        worker.write_text(
            "import os, sys, time\n"
            "from pathlib import Path\n"
            "entered, release = map(Path, sys.argv[1:3])\n"
            "with entered.open('a', encoding='utf-8') as handle:\n"
            "    handle.write('entered\\n'); handle.flush(); os.fsync(handle.fileno())\n"
            "deadline = time.time() + 8\n"
            "while not release.exists() and time.time() < deadline: time.sleep(0.02)\n"
            "print('OK')\n",
            encoding="utf-8",
        )
        workflow = self.write_workflow(
            "identity-v48-concurrent",
            [
                {"id": "gate", "kind": "external", "depends_on": []},
                {
                    "id": "slow",
                    "kind": "command",
                    "depends_on": ["gate"],
                    "argv": [
                        "{python}",
                        "{root}/scripts/slow_worker.py",
                        "{run_dir}/entered.txt",
                        "{run_dir}/release.txt",
                    ],
                    "expected": "exit_zero",
                },
            ],
        )
        run_dir = self.fixture.root / "evals" / "runs" / "v48-concurrent"
        started = self.controller(
            "run",
            "--workflow",
            str(workflow),
            "--run-dir",
            str(run_dir),
            "--run-id",
            "v48-concurrent",
            "--candidate-id",
            "candidate-v48-concurrent",
        )
        self.assertEqual(2, started.returncode, started.stdout + started.stderr)
        receipt = self.external_receipt("v48-concurrent", "gate", "v48-concurrent")
        completed = self.controller(
            "complete-external",
            "--run-dir",
            str(run_dir),
            "--step-id",
            "gate",
            "--receipt",
            str(receipt),
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

        first = subprocess.Popen(
            self.argv("resume", "--run-dir", str(run_dir)),
            cwd=CONTROLLER.parent.parent,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        entered = run_dir / "entered.txt"
        deadline = time.time() + 5
        while time.time() < deadline and not entered.exists():
            time.sleep(0.02)
        self.assertTrue(entered.exists(), "first resume never entered the worker")
        second = subprocess.Popen(
            self.argv("resume", "--run-dir", str(run_dir)),
            cwd=CONTROLLER.parent.parent,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.4)
        (run_dir / "release.txt").write_text("release\n", encoding="utf-8")
        first_stdout, first_stderr = first.communicate(timeout=10)
        second_stdout, second_stderr = second.communicate(timeout=10)
        results = [
            (first.returncode, first_stdout, first_stderr),
            (second.returncode, second_stdout, second_stderr),
        ]

        self.assertEqual(1, entered.read_text(encoding="utf-8").count("entered"))
        self.assertEqual([0, 3], sorted(code for code, _, _ in results))
        locked = [
            result_payload(
                subprocess.CompletedProcess(self.argv(), code, stdout, stderr)
            )
            for code, stdout, stderr in results
            if code == 3
        ]
        self.assertEqual(1, len(locked))
        self.assertIn("evolution_run_locked", set(locked[0].get("errors", [])))
        status = self.controller("status", "--run-dir", str(run_dir))
        self.assertEqual(0, status.returncode, status.stdout + status.stderr)


if __name__ == "__main__":
    unittest.main()
