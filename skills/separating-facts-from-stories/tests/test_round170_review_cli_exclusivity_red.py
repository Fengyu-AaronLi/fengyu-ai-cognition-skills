#!/usr/bin/env python3
"""Round 170 RED: the generic host CLI cannot originate release reviews."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HOST_PATH = (
    ROOT
    / "skills"
    / "separating-facts-from-stories"
    / "scripts"
    / "codex_exec_host.py"
)


def load_host():
    spec = importlib.util.spec_from_file_location("round170_host", HOST_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load host runtime")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Round170ReviewCliExclusivityRedTests(unittest.TestCase):
    def test_generic_run_cli_rejects_review_kind(self) -> None:
        host = load_host()
        with tempfile.TemporaryDirectory(prefix="sffs-round170-red-") as temp_dir:
            root = Path(temp_dir).resolve()
            prompt = root / "prompt.txt"
            prompt.write_text("friendly review\n", encoding="utf-8")
            stream = StringIO()
            with redirect_stdout(stream):
                status = host.main(
                    [
                        "run",
                        "--codex",
                        "/bin/echo",
                        "--prompt",
                        str(prompt),
                        "--output-dir",
                        str(root / "output"),
                        "--cwd",
                        str(root),
                        "--kind",
                        "review",
                        "--subject-id",
                        "p0_zero",
                        "--model",
                        host.REVIEW_MODEL,
                        "--reasoning-effort",
                        host.REVIEW_REASONING_EFFORT,
                        "--sandbox",
                        host.REVIEW_SANDBOX,
                        "--source-sha256",
                        "a" * 64,
                    ]
                )
            self.assertEqual(2, status)
            self.assertEqual(
                "FIXED_REVIEW_RUNNER_REQUIRED",
                json.loads(stream.getvalue())["error"],
            )
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()
