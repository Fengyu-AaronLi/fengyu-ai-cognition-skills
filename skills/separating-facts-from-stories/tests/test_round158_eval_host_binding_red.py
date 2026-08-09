#!/usr/bin/env python3
"""Round 158 RED: host, not the model, authors prepared case-result identity."""

from __future__ import annotations

import importlib.util
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
HOST_PATH = SKILL_DIR / "scripts" / "codex_exec_host.py"
HOST_RUNNER_PATH = SKILL_DIR / "scripts" / "host_eval_runner.py"
RUNNER_PATH = SKILL_DIR / "scripts" / "run_evals.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Round158EvalHostBindingRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host = load(HOST_PATH, "round158_host")
        cls.host_runner = load(HOST_RUNNER_PATH, "round158_host_runner")
        cls.runner = load(RUNNER_PATH, "round158_runner")

    def fake_codex(self, root: Path, message: str) -> Path:
        executable = root / "fake-codex"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json,pathlib,sys\n"
            "if '--version' in sys.argv:\n"
            " print('codex-cli fixture')\n"
            " raise SystemExit(0)\n"
            f"message={message!r}\n"
            "flag='--output-last-message'\n"
            "target=pathlib.Path(sys.argv[sys.argv.index(flag)+1])\n"
            "target.write_text(message,encoding='utf-8')\n"
            "events=[\n"
            " {'type':'thread.started','thread_id':'thread-eval-binding'},\n"
            " {'type':'turn.started'},\n"
            " {'type':'item.completed','item':{'type':'agent_message','text':message}},\n"
            " {'type':'turn.completed'},\n"
            "]\n"
            "for event in events: print(json.dumps(event))\n",
            encoding="utf-8",
        )
        executable.chmod(
            executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        return executable

    def test_binder_derives_case_result_from_host_receipt(self) -> None:
        case_id = "translation-non-trigger"
        message = "The meeting has been moved to Friday at 3 p.m."
        with tempfile.TemporaryDirectory(prefix="sffs-round158-") as temp_dir:
            root = Path(temp_dir) / "eval"
            self.runner.prepare_root(root)
            case_dir = root / case_id
            self.host_runner.prepare_runtime_materials(
                eval_root=root,
                case_dir=case_dir,
                case_id=case_id,
            )
            prompt = root / ".control" / case_id / "host-prompt.txt"
            prompt.parent.mkdir(parents=True)
            prompt.write_text(
                self.host.build_eval_prompt(
                    eval_root=root,
                    case_dir=case_dir,
                    case_id=case_id,
                ),
                encoding="utf-8",
            )
            receipt = self.host.run_codex_execution(
                codex_path=self.fake_codex(Path(temp_dir), message),
                prompt_path=prompt,
                output_dir=root / ".host" / case_id,
                cwd=case_dir,
                execution_kind="eval",
                subject_id=case_id,
                model=self.host.EVAL_MODEL,
                reasoning_effort=self.host.EVAL_REASONING_EFFORT,
                sandbox=self.host.EVAL_SANDBOX,
                timeout_seconds=10,
                input_path=case_dir / "input.json",
                context_path=root / self.runner.EVALUATION_CONTEXT_FILE,
                source_sha256=self.runner.runtime_snapshot_sha256(root),
            )
            result_path = self.host.bind_eval_case_result(
                receipt_path=receipt,
                eval_root=root,
                case_id=case_id,
            )
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual("host-", result["model_environment"]["runner"][:5])
            self.assertEqual("thread-eval-binding", result["model_environment"]["execution_id"])
            self.assertEqual("raw-output.txt", result["raw_output_path"])
            self.assertEqual([], result["artifact_paths"])
            self.assertEqual([], result["receipt_paths"])
            audit = self.runner.audit_case_result(
                root, case_id, self.runner.EXPECTED_CASES[case_id]
            )
            self.assertTrue(audit["valid"], audit)

            with self.assertRaises(FileExistsError):
                self.host.bind_eval_case_result(
                    receipt_path=receipt,
                    eval_root=root,
                    case_id=case_id,
                )


if __name__ == "__main__":
    unittest.main()
