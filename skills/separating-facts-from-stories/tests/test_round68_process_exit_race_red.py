from __future__ import annotations

import errno
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _FailingSysctl:
    def sysctl(self, *_args):
        return -1


class _PsGoneResult:
    returncode = 1

    def communicate(self, timeout=None):
        return "", "process no longer exists"


class Round68ProcessExitRaceRedTests(unittest.TestCase):
    MODULES = (
        ("producer", SKILL_DIR / "scripts" / "produce_release_gate.py"),
        ("controller", SKILL_DIR / "scripts" / "improvement_loop.py"),
    )

    def test_pid_disappearing_between_kill_probe_and_ps_is_absent(self) -> None:
        """A normal cleanup race must not replace the original timeout result."""
        for label, path in self.MODULES:
            with self.subTest(module=label):
                module = load_module(f"round68_{label}", path)
                kill_results = iter(
                    (
                        None,
                        ProcessLookupError(errno.ESRCH, "gone after first probe"),
                    )
                )

                def kill_side_effect(_pid: int, _signal: int):
                    result = next(kill_results)
                    if isinstance(result, BaseException):
                        raise result
                    return result

                with mock.patch.object(
                    module.ctypes, "CDLL", return_value=_FailingSysctl()
                ), mock.patch.object(
                    module.ctypes, "get_errno", return_value=errno.EINVAL
                ), mock.patch.object(
                    module.os, "kill", side_effect=kill_side_effect
                ) as kill, mock.patch.object(
                    module.subprocess, "Popen", return_value=_PsGoneResult()
                ):
                    self.assertIsNone(module._darwin_process_environment(424242))
                self.assertEqual(2, kill.call_count)


if __name__ == "__main__":
    unittest.main()
