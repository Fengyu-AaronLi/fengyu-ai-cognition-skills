#!/usr/bin/env python3
"""Round 180 RED: bind visible output to runtime bytes with one LF tolerance."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
HOST_PATH = SKILL_DIR / "scripts" / "codex_exec_host.py"
AUDITOR_PATH = SKILL_DIR / "scripts" / "run_evals.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Round180TerminalOutputBindingRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host = load(HOST_PATH, "round180_codex_exec_host")
        cls.auditor = load(AUDITOR_PATH, "round180_eval_auditor")

    def test_only_one_terminal_lf_transport_difference_is_allowed(self) -> None:
        for left, right in ((b"answer", b"answer"), (b"answer", b"answer\n")):
            with self.subTest(left=left, right=right):
                self.assertTrue(self.host.terminal_output_equal(left, right))
                self.assertTrue(
                    self.auditor.terminal_output_equal(
                        left.decode("utf-8"), right.decode("utf-8")
                    )
                )
        for left, right in (
            (b"answer", b"answer\n\n"),
            (b"answer", b"answer "),
            (b"answer", b"different"),
        ):
            with self.subTest(left=left, right=right):
                self.assertFalse(self.host.terminal_output_equal(left, right))

    def test_safety_output_must_bind_to_safety_template_not_casefile_renderer(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round180-safety-") as temp_dir:
            case_dir = Path(temp_dir) / "case"
            workspace = case_dir / ".runtime/workspace-1"
            workspace.mkdir(parents=True)
            safety = "现在请立即前往有人值守的安全地点。\n"
            renderer = "# 先处理现实安全\n\n这不是可见安全模板。\n"
            (workspace / "safety-response.md").write_text(safety, encoding="utf-8")
            (workspace / "response.md").write_text(renderer, encoding="utf-8")
            layout = {
                "input_paths": [".runtime/input-1.txt"],
                "workspace_paths": [".runtime/workspace-1"],
                "validation_paths": [],
            }

            self.host.assert_runtime_final_output(
                case_dir=case_dir,
                case_id="immediate-safety-override",
                layout=layout,
                observed_output=safety.rstrip("\n").encode("utf-8"),
            )
            with self.assertRaisesRegex(
                self.host.HostExecutionError,
                "EVAL_FINAL_RESPONSE_WORKSPACE_MISMATCH",
            ):
                self.host.assert_runtime_final_output(
                    case_dir=case_dir,
                    case_id="immediate-safety-override",
                    layout=layout,
                    observed_output=renderer.encode("utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
