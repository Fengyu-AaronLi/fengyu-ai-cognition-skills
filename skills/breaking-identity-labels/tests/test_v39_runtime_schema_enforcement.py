#!/usr/bin/env python3
"""V39 contracts proving schemas are executable gates, not documentation."""

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


def errors(result: subprocess.CompletedProcess[str]) -> set[str]:
    value = json.loads(result.stdout) if result.stdout.strip() else {}
    return set(value.get("errors", []))


class SchemaGateFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        for relative in (
            "scripts",
            "schemas",
            "tests",
            "workflows",
            "evals/runs",
            "examples/real-run",
        ):
            (root / relative).mkdir(parents=True, exist_ok=True)
        files = {
            "scripts/identity_label_case.py": "print('runtime')\n",
            "scripts/run_evolution.py": "# controller governance fixture\n",
            "scripts/build_demo.py": "# demo builder governance fixture\n",
            "evals/validate.py": "# evaluator governance fixture\n",
            "scripts/worker.py": "print('OK')\n",
            "tests/test_v39_contract.py": "# frozen contract\n",
        }
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        (root / "scripts" / "build_package.py").write_text(
            "import json\nprint(json.dumps({'tree_sha256': 'f' * 64}))\n",
            encoding="utf-8",
        )
        write_json(root / "schemas" / "case.schema.json", {"type": "object"})
        for name in DEMO_FILES:
            (root / "examples" / "real-run" / name).write_text(
                f"fixture:{name}\n",
                encoding="utf-8",
            )
        test_path = root / "tests" / "test_v39_contract.py"
        self.manifest = root / "evals" / "test-generation-manifest.json"
        write_json(
            self.manifest,
            {
                "schema_version": "1.0",
                "generation_rules": [
                    {"generation": "v39", "minimum": 1, "pattern": "tests/test_v39_*.py"}
                ],
                "files": [
                    {
                        "generation": "v39",
                        "path": "tests/test_v39_contract.py",
                        "sha256": digest(test_path),
                    }
                ],
            },
        )
        self.workflow = root / "workflows" / "schema.json"
        write_json(
            self.workflow,
            {
                "schema_version": "1.0",
                "workflow_id": "identity-v39-schema-gate",
                "description": "valid workflow",
                "steps": [
                    {
                        "id": "green",
                        "kind": "command",
                        "depends_on": [],
                        "argv": ["{python}", "{root}/scripts/worker.py"],
                        "expected": "exit_zero",
                    }
                ],
            },
        )
        self.run_dir = root / "evals" / "runs" / "schema"
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

    def run(self) -> subprocess.CompletedProcess[str]:
        return self.controller(
            "run",
            "--workflow",
            str(self.workflow),
            "--run-dir",
            str(self.run_dir),
            "--run-id",
            "v39-run",
            "--candidate-id",
            "candidate-v39",
        )

    def rewrite_events(self, receipt_sha256: str) -> None:
        path = self.run_dir / "events.jsonl"
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        previous = None
        rendered: list[bytes] = []
        for index, event in enumerate(events, start=1):
            event["event_id"] = index
            event["previous_event_sha256"] = previous
            if event["event_type"] == "command_completed":
                event["data"]["receipt_sha256"] = receipt_sha256
            event.pop("event_sha256", None)
            event["event_sha256"] = hashlib.sha256(canonical_bytes(event)).hexdigest()
            previous = event["event_sha256"]
            rendered.append(canonical_bytes(event))
        path.write_bytes(b"\n".join(rendered) + b"\n")
        state_path = self.run_dir / "run-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["event_count"] = len(events)
        state["event_head_sha256"] = previous
        state["steps"]["green"]["receipt_sha256"] = receipt_sha256
        write_json(state_path, state)


class RuntimeSchemaEnforcementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v39-schema-")
        self.fixture = SchemaGateFixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_workflow_schema_rejects_a_non_string_description(self) -> None:
        workflow = json.loads(self.fixture.workflow.read_text(encoding="utf-8"))
        workflow["description"] = 39
        write_json(self.fixture.workflow, workflow)

        result = self.fixture.run()

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("evolution_workflow_schema_invalid", errors(result))
        self.assertFalse(self.fixture.run_dir.exists())

    def test_run_state_schema_rejects_an_unknown_projection_field(self) -> None:
        self.assertEqual(0, self.fixture.run().returncode)
        state_path = self.fixture.run_dir / "run-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["forged_extra"] = True
        write_json(state_path, state)

        result = self.fixture.controller("status", "--run-dir", str(self.fixture.run_dir))

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("evolution_run_state_schema_invalid", errors(result))

    def test_command_receipt_schema_rejects_a_wrong_recorded_at_type(self) -> None:
        self.assertEqual(0, self.fixture.run().returncode)
        receipt_path = self.fixture.run_dir / "receipts" / "green.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["recorded_at"] = 39
        write_json(receipt_path, receipt)
        receipt_sha256 = digest(receipt_path)
        self.fixture.rewrite_events(receipt_sha256)

        result = self.fixture.controller("status", "--run-dir", str(self.fixture.run_dir))

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("evolution_command_receipt_schema_invalid", errors(result))

    def test_release_gate_schema_rejects_an_unknown_top_level_field(self) -> None:
        self.assertEqual(0, self.fixture.run().returncode)
        frozen = self.fixture.controller(
            "freeze",
            "--candidate-id",
            "candidate-v39",
            "--workflow",
            str(self.fixture.workflow),
            "--completed-run-dir",
            str(self.fixture.run_dir),
        )
        self.assertEqual(0, frozen.returncode, frozen.stdout + frozen.stderr)
        state = json.loads(self.fixture.release_state.read_text(encoding="utf-8"))
        state["forged_extra"] = True
        write_json(self.fixture.release_state, state)

        result = self.fixture.controller("check", "--allow-blocked")

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("release_gate_schema_invalid", errors(result))


if __name__ == "__main__":
    unittest.main()
