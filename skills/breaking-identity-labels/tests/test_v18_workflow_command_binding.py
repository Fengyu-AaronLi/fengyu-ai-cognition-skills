#!/usr/bin/env python3
"""V18 red contract: executable workflow scripts belong to the governance hash."""

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


class WorkflowCommandBindingTests(unittest.TestCase):
    def test_command_script_drift_invalidates_frozen_candidate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v18-command-binding-") as temp:
            root = Path(temp)
            for relative in (
                "scripts",
                "schemas",
                "tests",
                "workflows",
                "evals",
                "examples/real-run",
            ):
                (root / relative).mkdir(parents=True, exist_ok=True)
            sources = {
                "scripts/identity_label_case.py": "print('runtime')\n",
                "scripts/run_evolution.py": "# controller\n",
                "scripts/build_demo.py": "# demo builder\n",
                "evals/validate.py": "# evaluator\n",
                "scripts/worker.py": "print('original workflow check')\n",
            }
            for relative, content in sources.items():
                (root / relative).write_text(content, encoding="utf-8")
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
            test_path = root / "tests" / "test_v18_contract.py"
            test_path.write_text("# frozen contract\n", encoding="utf-8")
            manifest = root / "evals" / "test-generation-manifest.json"
            write_json(
                manifest,
                {
                    "schema_version": "1.0",
                    "generation_rules": [
                        {
                            "generation": "v18",
                            "minimum": 1,
                            "pattern": "tests/test_v18_*.py",
                        }
                    ],
                    "files": [
                        {
                            "generation": "v18",
                            "path": "tests/test_v18_contract.py",
                            "sha256": digest(test_path),
                        }
                    ],
                },
            )
            workflow = root / "workflows" / "v18.json"
            write_json(
                workflow,
                {
                    "schema_version": "1.0",
                    "workflow_id": "identity-v18-command-binding",
                    "steps": [
                        {
                            "id": "check",
                            "kind": "command",
                            "depends_on": [],
                            "argv": ["{python}", "{root}/scripts/worker.py"],
                            "expected": "exit_zero",
                        }
                    ],
                },
            )
            state = root / "evals" / "release-gate.json"

            def controller(*args: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [
                        sys.executable,
                        str(CONTROLLER),
                        *args,
                        "--root",
                        str(root),
                        "--state",
                        str(state),
                        "--test-manifest",
                        str(manifest),
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )

            completed_run = root / "evals" / "runs" / "v18-completed"
            executed = controller(
                "run",
                "--workflow",
                str(workflow),
                "--run-dir",
                str(completed_run),
                "--run-id",
                "v18-completed",
                "--candidate-id",
                "candidate-v18",
            )
            self.assertEqual(0, executed.returncode, executed.stdout + executed.stderr)
            frozen = controller(
                "freeze",
                "--candidate-id",
                "candidate-v18",
                "--workflow",
                str(workflow),
                "--completed-run-dir",
                str(completed_run),
            )
            self.assertEqual(0, frozen.returncode, frozen.stdout + frozen.stderr)
            worker = root / "scripts" / "worker.py"
            worker.write_text("print('changed workflow check')\n", encoding="utf-8")
            checked = controller("check", "--allow-blocked")
            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
            payload = json.loads(checked.stdout)
            self.assertEqual("invalid_run", payload["effective_decision"])
            self.assertEqual([], payload["errors"])
            self.assertIn("governance_tree_sha256_drift", payload["invalidations"])


if __name__ == "__main__":
    unittest.main()
