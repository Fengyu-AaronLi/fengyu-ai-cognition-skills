#!/usr/bin/env python3
"""Round 178 RED: non-trigger output still traverses the bounded passthrough runtime."""

from __future__ import annotations

import importlib.util
import json
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


class Round178HostPassthroughMaterializationRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load(RUNNER_PATH, "round178_host_eval_runner")
        cls.auditor = load(AUDITOR_PATH, "round178_eval_auditor")

    def fake_codex(self, root: Path, message: str) -> Path:
        executable = root / "codex"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json,pathlib,sys\n"
            "if '--version' in sys.argv:\n"
            " print('codex-cli round178 fixture')\n"
            " raise SystemExit(0)\n"
            f"message={message!r}\n"
            "target=pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
            "target.write_text(message,encoding='utf-8')\n"
            "for event in [\n"
            " {'type':'thread.started','thread_id':'thread-round178'},\n"
            " {'type':'turn.started'},\n"
            " {'type':'item.completed','item':{'type':'agent_message','text':message}},\n"
            " {'type':'turn.completed'}]: print(json.dumps(event))\n",
            encoding="utf-8",
        )
        executable.chmod(
            executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        return executable

    def test_translation_and_timeline_have_one_host_reserved_workspace(self) -> None:
        for case_id in ("translation-non-trigger", "sourced-timeline-passthrough"):
            with self.subTest(case_id=case_id):
                layout = self.runner.HOST.eval_runtime_layout(case_id)
                self.assertEqual([".runtime/workspace-1"], layout["workspace_paths"])

    def test_runner_materializes_and_audits_passthrough_state_from_observed_output(self) -> None:
        case_id = "translation-non-trigger"
        message = "The meeting has been moved to Friday at 3 p.m."
        with tempfile.TemporaryDirectory(prefix="sffs-round178-pass-") as temp_dir:
            temp = Path(temp_dir)
            root = temp / "eval"
            self.auditor.prepare_root(root)

            result = self.runner.run_case(
                eval_root=root,
                case_id=case_id,
                codex_path=self.fake_codex(temp, message),
            )

            case_dir = root / case_id
            workspace = case_dir / ".runtime/workspace-1"
            state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
            validation = json.loads(
                (workspace / "passthrough-validation.json").read_text(encoding="utf-8")
            )
            case_result = json.loads(
                (case_dir / "case-result.json").read_text(encoding="utf-8")
            )
            self.assertTrue(result["valid"], result)
            self.assertEqual("completed", state["phase"])
            self.assertTrue(validation["valid"])
            self.assertEqual([".runtime/workspace-1"], case_result["runtime_workspace_paths"])
            self.assertEqual(message, (workspace / "response.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
