#!/usr/bin/env python3
"""Round 167 RED: evals execute a prepared runtime snapshot, not live source."""

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


class Round167EvalRuntimeSnapshotRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host = load(HOST_PATH, "round167_host")
        cls.runner = load(RUNNER_PATH, "round167_host_eval_runner")
        cls.auditor = load(AUDITOR_PATH, "round167_eval_auditor")

    def fake_codex(self, root: Path) -> Path:
        executable = root / "codex"
        message = "The meeting has been moved to Friday at 3 p.m."
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json,pathlib,sys\n"
            "if '--version' in sys.argv:\n"
            " print('codex-cli snapshot fixture')\n"
            " raise SystemExit(0)\n"
            f"message={message!r}\n"
            "target=pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
            "target.write_text(message,encoding='utf-8')\n"
            "for event in [\n"
            " {'type':'thread.started','thread_id':'thread-runtime-snapshot'},\n"
            " {'type':'turn.started'},\n"
            " {'type':'item.completed','item':{'type':'agent_message','text':message}},\n"
            " {'type':'turn.completed'}]: print(json.dumps(event))\n",
            encoding="utf-8",
        )
        executable.chmod(
            executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        return executable

    def test_prepare_copies_hash_bound_runtime_and_prompt_uses_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round167-") as temp_dir:
            temp = Path(temp_dir)
            eval_root = temp / "eval"
            self.auditor.prepare_root(eval_root)
            snapshot_skill = eval_root / "runtime-snapshot" / "SKILL.md"
            manifest_path = eval_root / "runtime-snapshot-manifest.json"
            self.assertEqual(SKILL_DIR.joinpath("SKILL.md").read_bytes(), snapshot_skill.read_bytes())
            self.assertTrue(manifest_path.is_file())
            context = json.loads((eval_root / "evaluation-context.json").read_text())
            expected_source = context["runtime_snapshot"]["manifest_sha256"]
            prompt = self.host.build_eval_prompt(
                eval_root=eval_root,
                case_dir=eval_root / "translation-non-trigger",
                case_id="translation-non-trigger",
            )
            self.assertIn(str(snapshot_skill), prompt)
            self.assertNotIn(str(SKILL_DIR / "SKILL.md"), prompt)

            result = self.runner.run_case(
                eval_root=eval_root,
                case_id="translation-non-trigger",
                codex_path=self.fake_codex(temp),
            )
            self.assertTrue(result["valid"], result)
            receipt = json.loads(
                (eval_root / ".host" / "translation-non-trigger" / "host-execution-receipt.json").read_text()
            )
            self.assertEqual(expected_source, receipt["bindings"]["source_sha256"])


if __name__ == "__main__":
    unittest.main()
