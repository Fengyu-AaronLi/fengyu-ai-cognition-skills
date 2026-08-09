#!/usr/bin/env python3
"""Round 164 RED: input-only cases and host evidence need separate write roots."""

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


class Round164EvalHostBoundaryRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load(RUNNER_PATH, "round164_host_eval_runner")
        cls.auditor = load(AUDITOR_PATH, "round164_eval_auditor")

    def fake_codex(self, root: Path, counter: Path) -> Path:
        executable = root / "codex"
        message = "The meeting has been moved to Friday at 3 p.m."
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json,pathlib,sys\n"
            "if '--version' in sys.argv:\n"
            " print('codex-cli host-boundary fixture')\n"
            " raise SystemExit(0)\n"
            f"counter=pathlib.Path({str(counter)!r})\n"
            "counter.write_text('executed')\n"
            f"message={message!r}\n"
            "target=pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
            "target.write_text(message,encoding='utf-8')\n"
            "for event in [\n"
            " {'type':'thread.started','thread_id':'thread-host-boundary'},\n"
            " {'type':'turn.started'},\n"
            " {'type':'item.completed','item':{'type':'agent_message','text':message}},\n"
            " {'type':'turn.completed'}]: print(json.dumps(event))\n",
            encoding="utf-8",
        )
        executable.chmod(
            executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        return executable

    def test_preseeded_case_is_rejected_before_model_execution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round164-preseed-") as temp_dir:
            temp = Path(temp_dir)
            eval_root = temp / "eval"
            self.auditor.prepare_root(eval_root)
            case_dir = eval_root / "translation-non-trigger"
            (case_dir / "preseeded-answer.txt").write_text(
                "expected output", encoding="utf-8"
            )
            counter = temp / "counter.txt"
            with self.assertRaisesRegex(RuntimeError, "EVAL_CASE_NOT_INPUT_ONLY"):
                self.runner.run_case(
                    eval_root=eval_root,
                    case_id="translation-non-trigger",
                    codex_path=self.fake_codex(temp, counter),
                )
            self.assertFalse(counter.exists(), "model must not run on preseeded evidence")

    def test_host_receipt_and_prompt_are_outside_model_writable_case(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round164-host-") as temp_dir:
            temp = Path(temp_dir)
            eval_root = temp / "eval"
            self.auditor.prepare_root(eval_root)
            case_id = "translation-non-trigger"
            case_dir = eval_root / case_id
            result = self.runner.run_case(
                eval_root=eval_root,
                case_id=case_id,
                codex_path=self.fake_codex(temp, temp / "counter.txt"),
            )
            self.assertTrue(result["valid"], result)
            self.assertFalse((case_dir / "host").exists())
            self.assertFalse((case_dir / self.runner.PROMPT_FILENAME).exists())
            payload = json.loads((case_dir / "case-result.json").read_text())
            receipt = eval_root / payload["host_execution_receipt_path"]
            self.assertTrue(receipt.is_file())
            self.assertEqual(eval_root / ".host" / case_id, receipt.parent)


if __name__ == "__main__":
    unittest.main()
