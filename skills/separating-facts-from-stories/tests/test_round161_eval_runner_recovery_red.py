#!/usr/bin/env python3
"""Round 161 RED: a retained host result is bound once after a crash."""

from __future__ import annotations

import importlib.util
import os
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


class Round161EvalRunnerRecoveryRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load(RUNNER_PATH, "round161_host_eval_runner")
        cls.auditor = load(AUDITOR_PATH, "round161_eval_auditor")

    def counting_codex(self, root: Path, counter: Path) -> Path:
        executable = root / "codex"
        message = "The meeting has been moved to Friday at 3 p.m."
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json,pathlib,sys\n"
            "if '--version' in sys.argv:\n"
            " print('codex-cli recovery fixture')\n"
            " raise SystemExit(0)\n"
            f"counter=pathlib.Path({str(counter)!r})\n"
            "count=int(counter.read_text()) if counter.exists() else 0\n"
            "counter.write_text(str(count+1))\n"
            f"message={message!r}\n"
            "target=pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
            "target.write_text(message,encoding='utf-8')\n"
            "for event in [\n"
            " {'type':'thread.started','thread_id':'thread-recovery'},\n"
            " {'type':'turn.started'},\n"
            " {'type':'item.completed','item':{'type':'agent_message','text':message}},\n"
            " {'type':'turn.completed'}]: print(json.dumps(event))\n",
            encoding="utf-8",
        )
        executable.chmod(
            executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        return executable

    def test_crash_after_host_receipt_recovers_without_second_model_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round161-") as temp_dir:
            temp = Path(temp_dir)
            eval_root = temp / "eval"
            counter = temp / "count.txt"
            self.auditor.prepare_root(eval_root)
            codex = self.counting_codex(temp, counter)
            previous = os.environ.get("SFFS_HOST_EVAL_FAILPOINT")
            os.environ["SFFS_HOST_EVAL_FAILPOINT"] = "after_host_receipt"
            try:
                with self.assertRaisesRegex(RuntimeError, "after_host_receipt"):
                    self.runner.run_case(
                        eval_root=eval_root,
                        case_id="translation-non-trigger",
                        codex_path=codex,
                    )
            finally:
                if previous is None:
                    os.environ.pop("SFFS_HOST_EVAL_FAILPOINT", None)
                else:
                    os.environ["SFFS_HOST_EVAL_FAILPOINT"] = previous
            self.assertEqual("1", counter.read_text(encoding="utf-8"))
            result = self.runner.run_case(
                eval_root=eval_root,
                case_id="translation-non-trigger",
                codex_path=codex,
            )
            self.assertTrue(result["valid"], result)
            self.assertEqual("1", counter.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
