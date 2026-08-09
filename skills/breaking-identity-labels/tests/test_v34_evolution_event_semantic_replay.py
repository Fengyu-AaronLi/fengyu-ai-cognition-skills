#!/usr/bin/env python3
"""V34 contracts for semantic replay of the evolution event log."""

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


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def result_errors(result: subprocess.CompletedProcess[str]) -> set[str]:
    value = json.loads(result.stdout) if result.stdout.strip() else {}
    return set(value.get("errors", []))


class EventReplayFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        for relative in ("scripts", "workflows", "evals/runs", "evals/external"):
            (root / relative).mkdir(parents=True, exist_ok=True)
        (root / "scripts" / "red.py").write_text(
            "print('Ran 1 test')\nprint('FAILED (failures=1)')\nraise SystemExit(1)\n",
            encoding="utf-8",
        )
        (root / "scripts" / "green.py").write_text("print('OK')\n", encoding="utf-8")
        self.workflow = root / "workflows" / "loop.json"
        write_json(
            self.workflow,
            {
                "schema_version": "1.0",
                "workflow_id": "identity-v34-event-replay",
                "steps": [
                    {
                        "id": "targeted_red",
                        "kind": "command",
                        "depends_on": [],
                        "argv": ["{python}", "{root}/scripts/red.py"],
                        "expected": "red",
                    },
                    {
                        "id": "refinement",
                        "kind": "external",
                        "depends_on": ["targeted_red"],
                    },
                    {
                        "id": "targeted_green",
                        "kind": "command",
                        "depends_on": ["refinement"],
                        "argv": ["{python}", "{root}/scripts/green.py"],
                        "expected": "exit_zero",
                    },
                ],
            },
        )
        self.run_dir = root / "evals" / "runs" / "v34-complete"

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CONTROLLER), *args, "--root", str(self.root)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def complete(self) -> None:
        started = self.run(
            "run",
            "--workflow",
            str(self.workflow),
            "--run-dir",
            str(self.run_dir),
            "--run-id",
            "v34-complete",
            "--candidate-id",
            "candidate-v34",
        )
        if started.returncode != 2:
            raise AssertionError(started.stdout + started.stderr)
        external = self.root / "evals" / "external" / "refinement.json"
        write_json(
            external,
            {
                "schema_version": "1.0",
                "run_id": "v34-complete",
                "step_id": "refinement",
                "status": "completed",
                "summary": "independent refinement recorded",
                "evidence": [
                    {
                        "path": "scripts/green.py",
                        "sha256": digest(self.root / "scripts" / "green.py"),
                    }
                ],
            },
        )
        accepted = self.run(
            "complete-external",
            "--run-dir",
            str(self.run_dir),
            "--step-id",
            "refinement",
            "--receipt",
            str(external),
        )
        if accepted.returncode != 0:
            raise AssertionError(accepted.stdout + accepted.stderr)
        resumed = self.run("resume", "--run-dir", str(self.run_dir))
        if resumed.returncode != 0:
            raise AssertionError(resumed.stdout + resumed.stderr)

    def events(self) -> list[dict]:
        return [
            json.loads(line)
            for line in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def rewrite(self, events: list[dict]) -> None:
        previous = None
        rendered: list[bytes] = []
        for index, original in enumerate(events, start=1):
            event = dict(original)
            event["event_id"] = index
            event["previous_event_sha256"] = previous
            event.pop("event_sha256", None)
            event["event_sha256"] = hashlib.sha256(canonical_bytes(event)).hexdigest()
            previous = event["event_sha256"]
            rendered.append(canonical_bytes(event))
        (self.run_dir / "events.jsonl").write_bytes(b"\n".join(rendered) + b"\n")
        state_path = self.run_dir / "run-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["event_count"] = len(events)
        state["event_head_sha256"] = previous
        write_json(state_path, state)

    def status(self) -> subprocess.CompletedProcess[str]:
        return self.run("status", "--run-dir", str(self.run_dir))


class EvolutionEventSemanticReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v34-event-replay-")
        self.fixture = EventReplayFixture(Path(self.temporary.name))
        self.fixture.complete()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_complete_projection_requires_a_unique_final_run_completed_event(self) -> None:
        events = self.fixture.events()
        self.assertEqual("run_completed", events[-1]["event_type"])
        self.fixture.rewrite(events[:-1])

        result = self.fixture.status()

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("evolution_event_terminal_invalid", result_errors(result))

    def test_every_event_is_bound_to_the_run_id_even_after_valid_rehash(self) -> None:
        events = self.fixture.events()
        events[2]["run_id"] = "another-run"
        self.fixture.rewrite(events)

        result = self.fixture.status()

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("evolution_event_run_binding_mismatch", result_errors(result))

    def test_a_step_cannot_have_two_terminal_events(self) -> None:
        events = self.fixture.events()
        duplicate = dict(events[-2])
        events.insert(-1, duplicate)
        self.fixture.rewrite(events)

        result = self.fixture.status()

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("evolution_event_terminal_invalid", result_errors(result))

    def test_dependency_completion_must_precede_the_child_terminal_event(self) -> None:
        events = self.fixture.events()
        by_type = {event["event_type"]: event for event in events}
        red_completed = next(
            event
            for event in events
            if event["event_type"] == "command_completed"
            and event["data"]["step_id"] == "targeted_red"
        )
        green_completed = next(
            event
            for event in events
            if event["event_type"] == "command_completed"
            and event["data"]["step_id"] == "targeted_green"
        )
        reordered = [
            by_type["run_started"],
            red_completed,
            by_type["external_action_required"],
            green_completed,
            by_type["external_action_completed"],
            by_type["run_completed"],
        ]
        self.assertEqual("targeted_green", reordered[3]["data"]["step_id"])
        self.fixture.rewrite(reordered)

        result = self.fixture.status()

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("evolution_event_sequence_invalid", result_errors(result))


if __name__ == "__main__":
    unittest.main()
