#!/usr/bin/env python3
"""Round 165 RED: lexical parent traversal cannot escape an evidence root."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
HOST_PATH = SKILL_DIR / "scripts" / "codex_exec_host.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Round165RepoPathEscapeRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host = load(HOST_PATH, "round165_host")

    def test_parent_traversal_is_rejected_after_path_resolution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round165-") as temp_dir:
            temp = Path(temp_dir)
            root = temp / "root"
            outside = temp / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "evidence.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(
                self.host.HostExecutionError, "REVIEW_EVIDENCE_OUTSIDE_REPOSITORY"
            ):
                self.host._repo_relative_regular_file(
                    root, Path("../outside/evidence.json")
                )


if __name__ == "__main__":
    unittest.main()
