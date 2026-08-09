from __future__ import annotations

import errno
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
PRODUCER_PATH = SKILL_DIR / "scripts" / "produce_release_gate.py"
CONTROLLER_PATH = SKILL_DIR / "scripts" / "improvement_loop.py"
TOKEN_ENV = "SFFS_RELEASE_PROCESS_FAMILY"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Round63ProcessCleanupRedTests(unittest.TestCase):
    maxDiff = None

    def test_original_group_eperm_does_not_skip_exact_family_cleanup(self) -> None:
        for label, path in (
            ("producer", PRODUCER_PATH),
            ("controller", CONTROLLER_PATH),
        ):
            with self.subTest(module=label):
                module = load_module(f"round63_eperm_{label}", path)
                with mock.patch.object(
                    module.os,
                    "killpg",
                    side_effect=PermissionError(errno.EPERM, "already inaccessible"),
                ), mock.patch.object(
                    module, "enumerate_process_family", return_value=[]
                ) as enumerate_family:
                    policy = module.clean_process_family(
                        "round63-token", original_pgid=987654
                    )
                self.assertTrue(policy["confirmed_empty"])
                self.assertGreaterEqual(enumerate_family.call_count, 1)

    def test_enumeration_matches_exact_environment_entry_not_command_text(self) -> None:
        for label, path in (
            ("producer", PRODUCER_PATH),
            ("controller", CONTROLLER_PATH),
        ):
            with self.subTest(module=label):
                module = load_module(f"round63_exact_{label}", path)
                token = f"round63-{uuid.uuid4().hex}"
                marker = f"{TOKEN_ENV}={token}"
                clean_env = dict(os.environ)
                clean_env.pop(TOKEN_ENV, None)
                argv_only = subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        "import time; time.sleep(10)",
                        marker,
                    ],
                    env=clean_env,
                )
                prefix_env = dict(clean_env)
                prefix_env[TOKEN_ENV] = token + "-different"
                prefix_only = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(10)"],
                    env=prefix_env,
                )
                exact_env = dict(clean_env)
                exact_env[TOKEN_ENV] = token
                exact = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(10)"],
                    env=exact_env,
                )
                try:
                    time.sleep(0.1)
                    observed = module.enumerate_process_family(token)
                    self.assertEqual([exact.pid], observed)
                    self.assertIsNone(argv_only.poll())
                    self.assertIsNone(prefix_only.poll())
                finally:
                    for process in (argv_only, prefix_only, exact):
                        if process.poll() is None:
                            process.send_signal(signal.SIGTERM)
                    for process in (argv_only, prefix_only, exact):
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=2)

    def test_parent_exit_detached_grandchild_pipe_is_cleaned_before_drain(self) -> None:
        producer = load_module("round63_pipe_receipt", PRODUCER_PATH)
        with tempfile.TemporaryDirectory(prefix="sffs-round63-pipe-") as temp_dir:
            root = Path(temp_dir)
            marker = root / "escaped-marker.txt"
            pid_file = root / "escaped-pid.txt"
            receipt_path = root / "receipt.json"
            child_code = (
                "import os,pathlib,signal,sys,time; "
                "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                "pathlib.Path(sys.argv[2]).write_text(str(os.getpid())); "
                "time.sleep(1.2); pathlib.Path(sys.argv[1]).write_text('escaped')"
            )
            script = root / "parent-exits.py"
            script.write_text(
                "import subprocess,sys\n"
                f"subprocess.Popen([sys.executable,'-c',{child_code!r},sys.argv[1],sys.argv[2]],"
                "start_new_session=True)\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "RECIPE_TIMEOUT"):
                producer.run_isolated_command(
                    step_id="detached-pipe-timeout",
                    script=script,
                    arguments=[str(marker), str(pid_file)],
                    cwd=root,
                    timeout_seconds=0.1,
                    receipt_path=receipt_path,
                )
            time.sleep(1.3)
            self.assertFalse(marker.exists())
            self.assertTrue(receipt_path.is_file())
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(
                {
                    "schema_version",
                    "recipe_version",
                    "step_id",
                    "argv",
                    "cwd",
                    "timeout_seconds",
                    "shell",
                    "environment_policy",
                    "exit_code",
                    "timed_out",
                    "stdout",
                    "stderr",
                    "process_family_policy",
                },
                set(receipt),
            )
            self.assertEqual("detached-pipe-timeout", receipt["step_id"])
            self.assertIsNone(receipt["exit_code"])
            self.assertTrue(receipt["timed_out"])
            self.assertIsInstance(receipt["stdout"], str)
            self.assertIsInstance(receipt["stderr"], str)
            self.assertTrue(receipt["process_family_policy"]["confirmed_empty"])
            self.assertEqual(
                "cooperative_inherited_token_not_os_sandbox",
                receipt["process_family_policy"]["trust_boundary"],
            )
            self.assertTrue(pid_file.is_file())
            child_pid = int(pid_file.read_text(encoding="utf-8"))
            self.assertFalse(process_exists(child_pid))


if __name__ == "__main__":
    unittest.main()
