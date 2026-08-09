#!/usr/bin/env python3
"""Round 162 RED: one fixed suite command resumes only audited case evidence."""

from __future__ import annotations

import importlib.util
import stat
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
RUNNER_PATH = SKILL_DIR / "scripts" / "host_eval_runner.py"
AUDITOR_PATH = SKILL_DIR / "scripts" / "run_evals.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Round162EvalSuiteOrchestratorRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load(RUNNER_PATH, "round162_host_eval_runner")
        cls.auditor = load(AUDITOR_PATH, "round162_eval_auditor")

    def translation_codex(self, root: Path) -> Path:
        executable = root / "codex"
        message = "The meeting has been moved to Friday at 3 p.m."
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json,pathlib,sys\n"
            "if '--version' in sys.argv:\n"
            " print('codex-cli suite fixture')\n"
            " raise SystemExit(0)\n"
            f"message={message!r}\n"
            "target=pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
            "target.write_text(message,encoding='utf-8')\n"
            "for event in [\n"
            " {'type':'thread.started','thread_id':'thread-suite-translation'},\n"
            " {'type':'turn.started'},\n"
            " {'type':'item.completed','item':{'type':'agent_message','text':message}},\n"
            " {'type':'turn.completed'}]: print(json.dumps(event))\n",
            encoding="utf-8",
        )
        executable.chmod(
            executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        return executable

    def test_suite_reuses_only_audited_valid_case_and_runs_the_rest(self) -> None:
        if not hasattr(self.runner, "run_suite"):
            self.fail("missing fixed run_suite orchestrator")
        with tempfile.TemporaryDirectory(prefix="sffs-round162-") as temp_dir:
            temp = Path(temp_dir)
            eval_root = temp / "eval"
            self.auditor.prepare_root(eval_root)
            codex = self.translation_codex(temp)
            first = self.runner.run_case(
                eval_root=eval_root,
                case_id="translation-non-trigger",
                codex_path=codex,
            )
            self.assertTrue(first["valid"], first)
            called: list[str] = []
            original = self.runner.run_case

            def observed_run_case(*, eval_root, case_id, codex_path):
                called.append(case_id)
                return {"case_id": case_id, "valid": False, "errors": []}

            self.runner.run_case = observed_run_case
            try:
                report = self.runner.run_suite(eval_root=eval_root, codex_path=codex)
            finally:
                self.runner.run_case = original
            self.assertEqual(["translation-non-trigger"], report["reused_case_ids"])
            self.assertNotIn("translation-non-trigger", called)
            self.assertEqual(
                set(self.auditor.EXPECTED_CASES) - {"translation-non-trigger"},
                set(called),
            )

    def test_cli_exposes_fixed_suite_without_arbitrary_execution_fields(self) -> None:
        if not hasattr(self.runner, "run_suite"):
            self.fail("missing fixed run_suite orchestrator")
        parsed = self.runner.parser().parse_args(
            ["run-suite", "--eval-root", "/tmp/eval"]
        )
        self.assertEqual("run-suite", parsed.command)
        for name in ("prompt", "shell", "argv", "case_result", "max_workers"):
            self.assertFalse(hasattr(parsed, name), name)


if __name__ == "__main__":
    unittest.main()
