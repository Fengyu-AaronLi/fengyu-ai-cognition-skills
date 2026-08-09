#!/usr/bin/env python3
"""Round 160 RED: eval workers may write only inside their own case directory."""

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


class Round160EvalWriteBoundaryRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load(RUNNER_PATH, "round160_host_eval_runner")
        cls.auditor = load(AUDITOR_PATH, "round160_eval_auditor")

    def boundary_checking_codex(self, root: Path, expected_cwd: Path) -> Path:
        executable = root / "codex"
        message = "The meeting has been moved to Friday at 3 p.m."
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json,pathlib,sys\n"
            "if '--version' in sys.argv:\n"
            " print('codex-cli boundary fixture')\n"
            " raise SystemExit(0)\n"
            f"expected={str(expected_cwd)!r}\n"
            "observed=sys.argv[sys.argv.index('--cd')+1]\n"
            "if pathlib.Path(observed).resolve()!=pathlib.Path(expected).resolve():\n"
            " print('wrong writable root',file=sys.stderr)\n"
            " raise SystemExit(7)\n"
            f"message={message!r}\n"
            "target=pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
            "target.write_text(message,encoding='utf-8')\n"
            "for event in [\n"
            " {'type':'thread.started','thread_id':'thread-write-boundary'},\n"
            " {'type':'turn.started'},\n"
            " {'type':'item.completed','item':{'type':'agent_message','text':message}},\n"
            " {'type':'turn.completed'}]: print(json.dumps(event))\n",
            encoding="utf-8",
        )
        executable.chmod(
            executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        return executable

    def test_codex_workspace_is_the_case_directory_not_live_skill_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round160-") as temp_dir:
            eval_root = Path(temp_dir) / "eval"
            self.auditor.prepare_root(eval_root)
            case_dir = eval_root / "translation-non-trigger"
            result = self.runner.run_case(
                eval_root=eval_root,
                case_id="translation-non-trigger",
                codex_path=self.boundary_checking_codex(Path(temp_dir), case_dir),
            )
            self.assertTrue(result["valid"], result)


if __name__ == "__main__":
    unittest.main()
