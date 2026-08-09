from __future__ import annotations

import errno
import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
PRODUCER_PATH = SKILL_DIR / "scripts" / "produce_release_gate.py"
CONTROLLER_PATH = SKILL_DIR / "scripts" / "improvement_loop.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FailingSysctl:
    def sysctl(self, *_args):
        return -1


class _PsResult:
    def __init__(self, *, returncode: int, stdout: str, stderr: str = "") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    def communicate(self, timeout: int):
        if timeout != 5:
            raise AssertionError(f"unexpected timeout: {timeout}")
        return self._stdout, self._stderr


class Round66DarwinProcessStateRedTests(unittest.TestCase):
    """Darwin EINVAL is ambiguous: only gone or zombie may be skipped."""

    MODULES = (
        ("producer", PRODUCER_PATH),
        ("controller", CONTROLLER_PATH),
    )

    def _call_with_procargs_errno(
        self,
        module,
        *,
        error: int,
        pid: int = 424242,
        ps_result: _PsResult | None = None,
        kill_side_effect=None,
    ):
        patches = [
            mock.patch.object(module.ctypes, "CDLL", return_value=_FailingSysctl()),
            mock.patch.object(module.ctypes, "get_errno", return_value=error),
            mock.patch.object(module.os, "kill", side_effect=kill_side_effect),
        ]
        if ps_result is not None:
            patches.append(
                mock.patch.object(module.subprocess, "Popen", return_value=ps_result)
            )
        with patches[0], patches[1], patches[2]:
            if len(patches) == 4:
                with patches[3] as popen:
                    result = module._darwin_process_environment(pid)
                    return result, popen
            return module._darwin_process_environment(pid), None

    def test_non_z_process_with_einval_is_rejected(self) -> None:
        for label, path in self.MODULES:
            with self.subTest(module=label):
                module = load_module(f"round66_non_z_{label}", path)
                with self.assertRaisesRegex(RuntimeError, "KERN_PROCARGS2.*EINVAL"):
                    self._call_with_procargs_errno(
                        module,
                        error=errno.EINVAL,
                        ps_result=_PsResult(returncode=0, stdout="424242 S+\n"),
                    )

    def test_zombie_with_einval_is_the_only_live_state_allowed(self) -> None:
        for state in ("Z", "Z+", "Zs"):
            for label, path in self.MODULES:
                with self.subTest(module=label, state=state):
                    module = load_module(f"round66_z_{label}_{state}", path)
                    result, popen = self._call_with_procargs_errno(
                        module,
                        error=errno.EINVAL,
                        ps_result=_PsResult(
                            returncode=0, stdout=f"424242 {state}\n"
                        ),
                    )
                    self.assertIsNone(result)
                    self.assertEqual(
                        ["/bin/ps", "-p", "424242", "-o", "pid=,state="],
                        popen.call_args.args[0],
                    )

    def test_esrch_is_allowed_without_a_state_probe(self) -> None:
        for label, path in self.MODULES:
            with self.subTest(module=label):
                module = load_module(f"round66_esrch_{label}", path)
                with mock.patch.object(module.subprocess, "Popen") as popen:
                    result, _ = self._call_with_procargs_errno(
                        module, error=errno.ESRCH
                    )
                self.assertIsNone(result)
                popen.assert_not_called()

    def test_einval_with_independently_disappeared_pid_is_allowed(self) -> None:
        for label, path in self.MODULES:
            with self.subTest(module=label):
                module = load_module(f"round66_gone_{label}", path)
                result, popen = self._call_with_procargs_errno(
                    module,
                    error=errno.EINVAL,
                    kill_side_effect=ProcessLookupError(errno.ESRCH, "gone"),
                )
                self.assertIsNone(result)
                self.assertIsNone(popen)

    def test_einval_state_probe_failure_is_fail_closed(self) -> None:
        for label, path in self.MODULES:
            with self.subTest(module=label):
                module = load_module(f"round66_ps_fail_{label}", path)
                with self.assertRaisesRegex(RuntimeError, "process state check failed"):
                    self._call_with_procargs_errno(
                        module,
                        error=errno.EINVAL,
                        ps_result=_PsResult(
                            returncode=2, stdout="", stderr="ps failed"
                        ),
                    )

    def test_einval_malformed_or_wrong_pid_state_is_fail_closed(self) -> None:
        malformed_outputs = (
            "",
            "424242\n",
            "not-a-pid S\n",
            "999999 Z\n",
            "424242 Z extra\n",
            "424242 Z\n424242 Z\n",
        )
        for stdout in malformed_outputs:
            for label, path in self.MODULES:
                with self.subTest(module=label, stdout=stdout):
                    module = load_module(
                        f"round66_malformed_{label}_{abs(hash(stdout))}", path
                    )
                    with self.assertRaisesRegex(
                        RuntimeError, "malformed process state"
                    ):
                        self._call_with_procargs_errno(
                            module,
                            error=errno.EINVAL,
                            ps_result=_PsResult(returncode=0, stdout=stdout),
                        )

    def test_einval_state_probe_spawn_error_is_fail_closed(self) -> None:
        for label, path in self.MODULES:
            with self.subTest(module=label):
                module = load_module(f"round66_ps_spawn_{label}", path)
                with mock.patch.object(
                    module.ctypes, "CDLL", return_value=_FailingSysctl()
                ), mock.patch.object(
                    module.ctypes, "get_errno", return_value=errno.EINVAL
                ), mock.patch.object(
                    module.os, "kill", return_value=None
                ), mock.patch.object(
                    module.subprocess,
                    "Popen",
                    side_effect=OSError(errno.EIO, "ps unavailable"),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "process state check failed"
                    ):
                        module._darwin_process_environment(424242)


if __name__ == "__main__":
    unittest.main()
