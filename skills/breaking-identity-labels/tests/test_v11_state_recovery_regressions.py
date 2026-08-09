#!/usr/bin/env python3
"""V11 red contracts for safe journal recovery and orphan staging cleanup."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
ANALYSIS = ROOT / "tests" / "fixtures" / "analysis-c01.json"
TEXT = "我是典型 I 人，所以我不适合带团队，也不可能做好公开表达。"
STATE_FILES = ("events.jsonl", "case.json", "events.head.json")
JOURNAL = ".case-transaction.json"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    if not result.stdout.strip():
        raise AssertionError(f"command did not return JSON:\n{result.stderr}")
    return json.loads(result.stdout)


def error_codes(result: subprocess.CompletedProcess[str]) -> set[str]:
    return {item["code"] for item in payload(result).get("errors", [])}


def init_case(case_dir: Path) -> None:
    result = run_cli(
        "init",
        "--text",
        TEXT,
        "--case-dir",
        str(case_dir),
        "--clock",
        "2026-08-06T23:00:00Z",
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)


def plan_case(case_dir: Path, clock: str = "2026-08-06T23:01:00Z") -> subprocess.CompletedProcess[str]:
    return run_cli(
        "plan",
        "--case-dir",
        str(case_dir),
        "--analysis",
        str(ANALYSIS),
        "--expected-revision",
        "0",
        "--clock",
        clock,
    )


def crash_after_first_stage(case_dir: Path, command: str) -> subprocess.CompletedProcess[str]:
    if command == "init":
        argv = [
            "init",
            "--text",
            TEXT,
            "--case-dir",
            str(case_dir),
            "--clock",
            "2026-08-06T23:00:00Z",
        ]
    else:
        argv = [
            "plan",
            "--case-dir",
            str(case_dir),
            "--analysis",
            str(ANALYSIS),
            "--expected-revision",
            "0",
            "--clock",
            "2026-08-06T23:01:00Z",
        ]
    wrapper = r'''
import importlib.util
import os
import sys

cli = sys.argv[1]
spec = importlib.util.spec_from_file_location("identity_v11_crash", cli)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
real_stage = module._stage_bytes

def crash(*args, **kwargs):
    real_stage(*args, **kwargs)
    os._exit(94)

module._stage_bytes = crash
sys.argv = [cli, *sys.argv[2:]]
module.main()
'''
    return subprocess.run(
        [sys.executable, "-c", wrapper, str(CLI), *argv],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def runtime_orphans(case_dir: Path) -> list[str]:
    return sorted(
        item.name
        for item in case_dir.iterdir()
        if item.name.startswith(".") and item.name.endswith(".tmp")
    )


def valid_committed_journal(case_dir: Path) -> dict:
    transaction_dir = case_dir / ".case-txn-aaaaaaaa"
    transaction_dir.mkdir()
    targets = []
    for name in STATE_FILES:
        raw = (case_dir / name).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        backup = f"{name}.before"
        (transaction_dir / backup).write_bytes(raw)
        targets.append(
            {
                "name": name,
                "old_exists": True,
                "old_sha256": digest,
                "new_sha256": digest,
                "backup": backup,
                "staged": f".{name}.aaaaaaaa.tmp",
            }
        )
    return {
        "schema_version": "1.0",
        "transaction_dir": transaction_dir.name,
        "targets": targets,
    }


def write_journal(case_dir: Path, journal: object) -> None:
    (case_dir / JOURNAL).write_text(
        json.dumps(journal, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


class V11StateRecoveryRegressions(unittest.TestCase):
    def test_init_recovers_a_runtime_stage_orphan_created_before_the_journal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v11-init-orphan-") as tmp:
            case_dir = Path(tmp) / "case"
            crashed = crash_after_first_stage(case_dir, "init")
            self.assertEqual(94, crashed.returncode)
            self.assertEqual(1, len(runtime_orphans(case_dir)))

            retry = run_cli(
                "init",
                "--text",
                TEXT,
                "--case-dir",
                str(case_dir),
                "--clock",
                "2026-08-06T23:00:01Z",
            )
            self.assertEqual(0, retry.returncode, retry.stdout + retry.stderr)
            self.assertEqual([], runtime_orphans(case_dir))
            replay = run_cli("replay", "--case-dir", str(case_dir))
            self.assertEqual(0, replay.returncode, replay.stdout + replay.stderr)

    def test_next_writer_cleans_a_runtime_stage_orphan_before_mutating(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v11-write-orphan-") as tmp:
            case_dir = Path(tmp) / "case"
            init_case(case_dir)
            crashed = crash_after_first_stage(case_dir, "plan")
            self.assertEqual(94, crashed.returncode)
            self.assertEqual(1, len(runtime_orphans(case_dir)))

            retry = plan_case(case_dir, "2026-08-06T23:01:01Z")
            self.assertEqual(0, retry.returncode, retry.stdout + retry.stderr)
            self.assertEqual([], runtime_orphans(case_dir))

    def test_init_still_refuses_unknown_files_and_runtime_named_symlinks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v11-unknown-") as tmp:
            root = Path(tmp)
            unknown_dir = root / "unknown-case"
            unknown_dir.mkdir()
            (unknown_dir / "notes.txt").write_text("user data", encoding="utf-8")
            unknown = run_cli(
                "init",
                "--text",
                TEXT,
                "--case-dir",
                str(unknown_dir),
                "--clock",
                "2026-08-06T23:00:00Z",
            )
            self.assertNotEqual(0, unknown.returncode)
            self.assertIn("case_directory_not_empty", error_codes(unknown))
            self.assertTrue((unknown_dir / "notes.txt").is_file())

            symlink_dir = root / "symlink-case"
            symlink_dir.mkdir()
            sentinel = root / "sentinel.txt"
            sentinel.write_text("keep", encoding="utf-8")
            orphan_link = symlink_dir / ".events.jsonl.aaaaaaaa.tmp"
            orphan_link.symlink_to(sentinel)
            linked = run_cli(
                "init",
                "--text",
                TEXT,
                "--case-dir",
                str(symlink_dir),
                "--clock",
                "2026-08-06T23:00:00Z",
            )
            self.assertNotEqual(0, linked.returncode)
            self.assertIn("case_directory_not_empty", error_codes(linked))
            self.assertTrue(orphan_link.is_symlink())
            self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))

    def test_malformed_journal_shapes_return_stable_json_errors(self) -> None:
        malformed = [
            ["not", "an", "object"],
            {"schema_version": "1.0", "transaction_dir": ".case-txn-aaaaaaaa", "targets": "bad"},
            {"schema_version": "1.0", "transaction_dir": ".case-txn-aaaaaaaa", "targets": [42]},
            {
                "schema_version": "1.0",
                "transaction_dir": ".case-txn-aaaaaaaa",
                "targets": [{"name": []}, {"name": "case.json"}, {"name": "events.head.json"}],
            },
        ]
        for index, journal in enumerate(malformed):
            with self.subTest(index=index), tempfile.TemporaryDirectory(prefix="identity-v11-shape-") as tmp:
                case_dir = Path(tmp) / "case"
                init_case(case_dir)
                (case_dir / ".case-txn-aaaaaaaa").mkdir()
                write_journal(case_dir, journal)
                result = plan_case(case_dir)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("transaction_journal_invalid", error_codes(result))
                self.assertNotIn("Traceback", result.stderr)

    def test_journal_rejects_unsafe_staged_transaction_and_backup_paths(self) -> None:
        mutations = (
            ("staged", lambda journal, outside: journal["targets"][0].__setitem__("staged", str(outside))),
            ("transaction_dir", lambda journal, outside: journal.__setitem__("transaction_dir", "../outside")),
            ("backup", lambda journal, outside: journal["targets"][0].__setitem__("backup", "../outside")),
        )
        for field, mutate in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory(prefix="identity-v11-path-") as tmp:
                root = Path(tmp)
                case_dir = root / "case"
                init_case(case_dir)
                sentinel = root / "outside"
                sentinel.write_text("keep", encoding="utf-8")
                journal = valid_committed_journal(case_dir)
                mutate(journal, sentinel)
                write_journal(case_dir, journal)

                result = plan_case(case_dir)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("transaction_journal_invalid", error_codes(result))
                self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))

    def test_journal_rejects_symlink_escape_without_touching_its_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v11-journal-link-") as tmp:
            root = Path(tmp)
            case_dir = root / "case"
            init_case(case_dir)
            sentinel = root / "outside-sentinel"
            sentinel.write_text("keep", encoding="utf-8")
            staged_link = case_dir / ".events.jsonl.aaaaaaaa.tmp"
            staged_link.symlink_to(sentinel)
            journal = valid_committed_journal(case_dir)
            journal["targets"][0]["staged"] = staged_link.name
            write_journal(case_dir, journal)

            result = plan_case(case_dir)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("transaction_journal_invalid", error_codes(result))
            self.assertTrue(staged_link.is_symlink())
            self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
