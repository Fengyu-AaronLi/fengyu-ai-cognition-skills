#!/usr/bin/env python3
"""Round 174 RED: real Python execution must not mutate the frozen snapshot."""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
AUDITOR_PATH = SKILL_DIR / "scripts" / "run_evals.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Round174RuntimeSnapshotBytecodeRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.auditor = load(AUDITOR_PATH, "round174_eval_auditor")

    def test_prepared_snapshot_is_filesystem_read_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round174-mode-") as temp_dir:
            eval_root = Path(temp_dir) / "eval"
            self.auditor.prepare_root(eval_root)
            snapshot = eval_root / "runtime-snapshot"
            for path in [snapshot, *snapshot.rglob("*")]:
                mode = stat.S_IMODE(path.stat().st_mode)
                self.assertEqual(0, mode & 0o222, path)

    def test_importing_snapshot_runtime_cannot_create_bytecode_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round174-pyc-") as temp_dir:
            eval_root = Path(temp_dir) / "eval"
            self.auditor.prepare_root(eval_root)
            runtime = eval_root / "runtime-snapshot" / "scripts" / "casefile.py"
            environment = os.environ.copy()
            environment.pop("PYTHONDONTWRITEBYTECODE", None)
            environment.pop("PYTHONPYCACHEPREFIX", None)
            command = (
                "import importlib.util; "
                f"p={str(runtime)!r}; "
                "s=importlib.util.spec_from_file_location('runtime_casefile',p); "
                "m=importlib.util.module_from_spec(s); s.loader.exec_module(m)"
            )
            completed = subprocess.run(
                [sys.executable, "-c", command],
                cwd=eval_root,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            _, errors = self.auditor.inspect_runtime_snapshot(eval_root)
            self.assertEqual([], errors)
            self.assertFalse(
                any(path.name == "__pycache__" for path in eval_root.rglob("*"))
            )


if __name__ == "__main__":
    unittest.main()
