#!/usr/bin/env python3
"""Round 177 RED: safety has one hash-bound user-visible terminal response."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
WORKFLOW = SKILL_DIR / "scripts" / "workflow.py"
AUDITOR_PATH = SKILL_DIR / "scripts" / "run_evals.py"
FIXTURE_PATH = SKILL_DIR / "tests" / "test_casefile.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Round177SafetyTerminalContractRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.auditor = load(AUDITOR_PATH, "round177_eval_auditor")
        cls.fixtures = load(FIXTURE_PATH, "round177_casefile_fixtures")

    def run_workflow(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(WORKFLOW), *arguments],
            cwd=SKILL_DIR,
            text=True,
            capture_output=True,
            check=False,
        )

    def completed_safety_workspace(self, root: Path) -> Path:
        case = self.fixtures.valid_safety()
        input_path = root / "input.txt"
        input_path.write_text(case["inputs"][0]["text"], encoding="utf-8")
        workspace = root / "workspace"
        started = self.run_workflow(
            "start",
            "--input",
            str(input_path),
            "--workspace",
            str(workspace),
            "--case-id",
            case["case_id"],
            "--mode",
            "safety",
        )
        self.assertEqual(0, started.returncode, started.stderr)
        template = self.run_workflow("safety-template", "--workspace", str(workspace))
        self.assertEqual(0, template.returncode, template.stderr)
        visible = root / "visible-safety.md"
        visible.write_text(template.stdout, encoding="utf-8")
        acknowledged = self.run_workflow(
            "acknowledge-safety",
            "--workspace",
            str(workspace),
            "--response",
            str(visible),
        )
        self.assertEqual(0, acknowledged.returncode, acknowledged.stderr)
        (workspace / "casefile.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        checked = self.run_workflow("check", "--workspace", str(workspace))
        self.assertEqual(0, checked.returncode, checked.stderr)
        finalized = self.run_workflow("finalize", "--workspace", str(workspace))
        self.assertEqual(0, finalized.returncode, finalized.stderr)
        return workspace

    def test_finalized_response_equals_acknowledged_safety_template(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round177-final-") as temp_dir:
            workspace = self.completed_safety_workspace(Path(temp_dir))
            self.assertEqual(
                (workspace / "safety-response.md").read_bytes(),
                (workspace / "response.md").read_bytes(),
            )

    def test_finalized_safety_output_passes_first_action_audit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round177-audit-") as temp_dir:
            workspace = self.completed_safety_workspace(Path(temp_dir))
            output = (workspace / "response.md").read_text(encoding="utf-8")
            errors: list[dict[str, str]] = []
            self.auditor._check_safety_output(
                "immediate-safety-override", output, errors
            )
            self.assertEqual([], errors)

    def test_shared_aggregate_span_does_not_cross_contaminate_signal_types(self) -> None:
        case = self.fixtures.valid_safety()
        errors = self.auditor._check_safety_core(
            case,
            {
                "今晚去你家堵你": "explicit_threat",
                "以前砸过我的门": "prior_violence_or_damage",
            },
        )
        self.assertNotIn(
            "RISK_SIGNAL_TYPE_WRONG",
            {item["code"] for item in errors},
            errors,
        )


if __name__ == "__main__":
    unittest.main()
