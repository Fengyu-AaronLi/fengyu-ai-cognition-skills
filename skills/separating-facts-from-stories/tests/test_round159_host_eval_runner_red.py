#!/usr/bin/env python3
"""Round 159 RED: fixed fresh-model eval runner, not manual case-result authoring."""

from __future__ import annotations

import importlib.util
import stat
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
RUNNER_PATH = SKILL_DIR / "scripts" / "host_eval_runner.py"
EVAL_AUDITOR_PATH = SKILL_DIR / "scripts" / "run_evals.py"


def load(path: Path, name: str):
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Round159HostEvalRunnerRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load(RUNNER_PATH, "round159_host_eval_runner")
        cls.auditor = load(EVAL_AUDITOR_PATH, "round159_eval_auditor")

    def fake_codex(self, root: Path) -> Path:
        message = "The meeting has been moved to Friday at 3 p.m."
        executable = root / "codex"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json,pathlib,sys\n"
            "if '--version' in sys.argv:\n"
            " print('codex-cli fixture')\n"
            " raise SystemExit(0)\n"
            f"message={message!r}\n"
            "target=pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
            "target.write_text(message,encoding='utf-8')\n"
            "for event in [\n"
            " {'type':'thread.started','thread_id':'thread-host-runner'},\n"
            " {'type':'turn.started'},\n"
            " {'type':'item.completed','item':{'type':'agent_message','text':message}},\n"
            " {'type':'turn.completed'}]: print(json.dumps(event))\n",
            encoding="utf-8",
        )
        executable.chmod(
            executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        return executable

    def test_fixed_runner_executes_and_audits_one_prepared_case(self) -> None:
        if self.runner is None:
            self.fail(f"missing fixed host eval runner: {RUNNER_PATH}")
        with tempfile.TemporaryDirectory(prefix="sffs-round159-") as temp_dir:
            eval_root = Path(temp_dir) / "eval"
            self.auditor.prepare_root(eval_root)
            result = self.runner.run_case(
                eval_root=eval_root,
                case_id="translation-non-trigger",
                codex_path=self.fake_codex(Path(temp_dir)),
            )
            self.assertTrue(result["valid"], result)
            self.assertEqual("translation-non-trigger", result["case_id"])
            self.assertTrue(
                (eval_root / "translation-non-trigger" / "case-result.json").is_file()
            )
            self.assertTrue(
                (eval_root / ".host" / "translation-non-trigger" / "host-execution-receipt.json").is_file()
            )

    def test_cli_has_no_prompt_command_or_case_result_override(self) -> None:
        if self.runner is None:
            self.fail(f"missing fixed host eval runner: {RUNNER_PATH}")
        parser = self.runner.parser()
        parsed = parser.parse_args(
            ["run", "--eval-root", "/tmp/eval", "--case-id", "case-a"]
        )
        self.assertEqual("run", parsed.command)
        for name in ("prompt", "shell", "argv", "case_result"):
            self.assertFalse(hasattr(parsed, name), name)


if __name__ == "__main__":
    unittest.main()
