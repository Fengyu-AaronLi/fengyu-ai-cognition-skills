from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
MODULES = (
    ("producer", SKILL_DIR / "scripts" / "produce_release_gate.py"),
    ("controller", SKILL_DIR / "scripts" / "improvement_loop.py"),
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _PsResult:
    def __init__(self, stdout: str, *, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    def communicate(self, timeout: int):
        if timeout != 5:
            raise AssertionError(f"unexpected timeout: {timeout}")
        return self._stdout, self._stderr


class Round71ProcessEnumerationFailClosedRedTests(unittest.TestCase):
    """Darwin process discovery must reject every malformed nonblank row."""

    def _enumerate(self, label: str, path: Path, stdout: str):
        module = load_module(f"round71_{label}_{abs(hash(stdout))}", path)
        own_uid = os.getuid()
        with mock.patch.object(module.sys, "platform", "darwin"), mock.patch.object(
            module.os, "getuid", return_value=own_uid
        ), mock.patch.object(
            module.subprocess, "Popen", return_value=_PsResult(stdout)
        ) as popen:
            result = module._same_uid_process_ids()
        self.assertEqual(
            ["/bin/ps", "-axo", "pid=,uid="], popen.call_args.args[0]
        )
        return result

    def test_valid_headerless_rows_and_blank_lines_are_accepted(self) -> None:
        own_uid = os.getuid()
        stdout = f"\n  101 {own_uid}\n\t\n202 {own_uid + 1}\n303 {own_uid}\n"
        for label, path in MODULES:
            with self.subTest(module=label):
                self.assertEqual([101, 303], self._enumerate(label, path, stdout))

    def test_wrong_field_count_is_fail_closed(self) -> None:
        own_uid = os.getuid()
        malformed_outputs = (
            f"101 {own_uid}\nmalformed\n",
            f"101 {own_uid}\n202 {own_uid} extra\n",
        )
        for stdout in malformed_outputs:
            for label, path in MODULES:
                with self.subTest(module=label, stdout=stdout):
                    with self.assertRaisesRegex(
                        RuntimeError, "malformed process enumeration output"
                    ):
                        self._enumerate(label, path, stdout)

    def test_nonnumeric_pid_or_uid_is_fail_closed(self) -> None:
        own_uid = os.getuid()
        malformed_outputs = (
            f"not-a-pid {own_uid}\n",
            "101 not-a-uid\n",
        )
        for stdout in malformed_outputs:
            for label, path in MODULES:
                with self.subTest(module=label, stdout=stdout):
                    with self.assertRaisesRegex(
                        RuntimeError, "malformed process enumeration output"
                    ):
                        self._enumerate(label, path, stdout)


if __name__ == "__main__":
    unittest.main()
