#!/usr/bin/env python3
"""V11 contracts for stateless compilation and explicit case operations."""

from __future__ import annotations

import copy
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
CLOCK = "2026-08-06T23:30:00Z"
PLAN_CLOCK = "2026-08-06T23:31:00Z"
STATE_FILES = ("events.jsonl", "case.json", "events.head.json")
JOURNAL = ".case-transaction.json"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class StatelessCompileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-compile-")
        self.root = Path(self.temporary.name)
        self.scaffold = self.root / "draft.json"
        result = run_cli(
            "scaffold",
            "--text",
            TEXT,
            "--case-id",
            "compile-c01",
            "--clock",
            CLOCK,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.draft = payload(result)
        self.scaffold.write_text(json.dumps(self.draft, ensure_ascii=False), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_compile_uses_plan_semantics_and_preserves_scaffold_owned_fields(self) -> None:
        output = self.root / "nested" / "case.json"
        result = run_cli(
            "compile",
            "--scaffold",
            str(self.scaffold),
            "--analysis",
            str(ANALYSIS),
            "--out",
            str(output),
            "--clock",
            PLAN_CLOCK,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        response = payload(result)
        self.assertEqual({"valid", "output", "case"}, set(response))
        self.assertTrue(response["valid"])
        self.assertEqual(str(output.resolve()), response["output"])
        case = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(response["case"], case)
        for field in (
            "schema_version",
            "case_id",
            "language",
            "created_at",
            "evidence",
            "route",
            "risk_flags",
        ):
            self.assertEqual(self.draft[field], case[field], field)
        self.assertEqual("planned", case["status"])
        self.assertEqual(1, case["revision"])
        self.assertEqual(PLAN_CLOCK, case["updated_at"])
        self.assertIsNone(case["review"])
        expected_analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))
        expected_analysis["experiment"]["started_at"] = None
        self.assertEqual(expected_analysis, case["analysis"])
        validated = run_cli("validate", str(output))
        self.assertEqual(0, validated.returncode, validated.stdout + validated.stderr)

    def test_compile_refuses_overwrite_without_changing_existing_output(self) -> None:
        output = self.root / "case.json"
        original = b'{"owned":"by-user"}\n'
        output.write_bytes(original)
        result = run_cli(
            "compile",
            "--scaffold",
            str(self.scaffold),
            "--analysis",
            str(ANALYSIS),
            "--out",
            str(output),
            "--clock",
            PLAN_CLOCK,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(original, output.read_bytes())
        self.assertIn("output_exists", {item["code"] for item in payload(result)["errors"]})

    def test_compile_validation_failure_writes_nothing(self) -> None:
        invalid_analysis = self.root / "invalid-analysis.json"
        analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))
        analysis["experiment"]["action"] = "停药七天观察表现"
        invalid_analysis.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
        output = self.root / "not-created" / "case.json"
        result = run_cli(
            "compile",
            "--scaffold",
            str(self.scaffold),
            "--analysis",
            str(invalid_analysis),
            "--out",
            str(output),
            "--clock",
            PLAN_CLOCK,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(output.exists())
        self.assertFalse(output.parent.exists())
        self.assertIn("medical_plan_change", {item["code"] for item in payload(result)["errors"]})

    def test_compile_rejects_a_tampered_scaffold_before_writing(self) -> None:
        tampered = copy.deepcopy(self.draft)
        tampered["route"] = {"mode": "deconstruct", "trigger": True, "reason_codes": ["forged"]}
        bad_scaffold = self.root / "tampered.json"
        bad_scaffold.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
        output = self.root / "case.json"
        result = run_cli(
            "compile",
            "--scaffold",
            str(bad_scaffold),
            "--analysis",
            str(ANALYSIS),
            "--out",
            str(output),
            "--clock",
            PLAN_CLOCK,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(output.exists())
        self.assertIn("route_evidence_mismatch", {item["code"] for item in payload(result)["errors"]})


class DoctorAndRecoverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-operations-")
        self.root = Path(self.temporary.name)
        self.case_dir = self.root / "case"
        result = run_cli(
            "init",
            "--text",
            TEXT,
            "--case-dir",
            str(self.case_dir),
            "--case-id",
            "operations-c01",
            "--clock",
            CLOCK,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def tree_snapshot(self) -> dict[str, bytes | str]:
        result: dict[str, bytes | str] = {}
        for item in sorted(self.case_dir.rglob("*")):
            relative = str(item.relative_to(self.case_dir))
            if item.is_symlink():
                result[relative] = f"symlink:{item.readlink()}"
            elif item.is_file():
                result[relative] = item.read_bytes()
            elif item.is_dir():
                result[relative] = "directory"
        return result

    def install_interrupted_transaction(self) -> dict[str, bytes]:
        before = {name: (self.case_dir / name).read_bytes() for name in STATE_FILES}
        transaction = self.case_dir / ".case-txn-abcdef"
        transaction.mkdir()
        targets = []
        for name, content in before.items():
            (transaction / f"{name}.before").write_bytes(content)
            staged_name = f".{name}.abcdef.tmp"
            staged = self.case_dir / staged_name
            staged.write_bytes(content + b"\ninterrupted")
            targets.append(
                {
                    "name": name,
                    "old_exists": True,
                    "old_sha256": sha256(content),
                    "new_sha256": sha256(staged.read_bytes()),
                    "backup": f"{name}.before",
                    "staged": staged_name,
                }
            )
        journal = {
            "schema_version": "1.0",
            "transaction_dir": transaction.name,
            "targets": targets,
        }
        (self.case_dir / JOURNAL).write_text(json.dumps(journal), encoding="utf-8")
        (self.case_dir / "case.json").write_bytes(b'{"interrupted":true}\n')
        return before

    def test_doctor_is_read_only_stable_and_checks_all_three_layers(self) -> None:
        before = self.tree_snapshot()
        first = run_cli("doctor", "--case-dir", str(self.case_dir))
        middle = self.tree_snapshot()
        second = run_cli("doctor", "--case-dir", str(self.case_dir))
        after = self.tree_snapshot()
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(before, middle)
        self.assertEqual(before, after)
        report = payload(first)
        self.assertEqual(
            {"valid", "case_dir", "journal", "replay", "materialized", "errors"},
            set(report),
        )
        self.assertTrue(report["valid"])
        self.assertEqual(
            {"present", "valid", "recovery_required", "errors"},
            set(report["journal"]),
        )
        self.assertFalse(report["journal"]["present"])
        self.assertTrue(report["journal"]["valid"])
        self.assertTrue(report["replay"]["valid"])
        self.assertTrue(report["materialized"]["valid"])
        self.assertEqual([], report["errors"])

    def test_doctor_reports_pending_valid_journal_without_recovering(self) -> None:
        self.install_interrupted_transaction()
        before = self.tree_snapshot()
        result = run_cli("doctor", "--case-dir", str(self.case_dir))
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, self.tree_snapshot())
        report = payload(result)
        self.assertFalse(report["valid"])
        self.assertTrue(report["journal"]["present"])
        self.assertTrue(report["journal"]["valid"])
        self.assertTrue(report["journal"]["recovery_required"])
        self.assertFalse(report["replay"]["valid"])
        self.assertFalse(report["materialized"]["valid"])
        self.assertIn("transaction_recovery_required", {item["code"] for item in report["errors"]})

    def test_doctor_missing_directory_does_not_create_it(self) -> None:
        missing = self.root / "missing"
        result = run_cli("doctor", "--case-dir", str(missing))
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(missing.exists())
        report = payload(result)
        self.assertEqual(
            {"valid", "case_dir", "journal", "replay", "materialized", "errors"},
            set(report),
        )
        self.assertIn("case_directory_missing", {item["code"] for item in report["errors"]})

    def test_recover_rolls_back_pending_transaction_then_replays(self) -> None:
        before = self.install_interrupted_transaction()
        result = run_cli("recover", "--case-dir", str(self.case_dir))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        report = payload(result)
        self.assertEqual({"valid", "case_dir", "recovered", "replay", "errors"}, set(report))
        self.assertTrue(report["valid"])
        self.assertTrue(report["recovered"])
        self.assertTrue(report["replay"]["valid"])
        self.assertEqual([], report["errors"])
        self.assertFalse((self.case_dir / JOURNAL).exists())
        self.assertFalse((self.case_dir / ".case-txn-abcdef").exists())
        for name, content in before.items():
            self.assertEqual(content, (self.case_dir / name).read_bytes(), name)

    def test_recover_without_pending_work_is_a_valid_noop(self) -> None:
        before = self.tree_snapshot()
        result = run_cli("recover", "--case-dir", str(self.case_dir))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        report = payload(result)
        self.assertTrue(report["valid"])
        self.assertFalse(report["recovered"])
        self.assertTrue(report["replay"]["valid"])
        self.assertEqual(before, self.tree_snapshot())

    def test_recover_missing_directory_does_not_create_it(self) -> None:
        missing = self.root / "missing"
        result = run_cli("recover", "--case-dir", str(missing))
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(missing.exists())
        self.assertIn("case_directory_missing", {item["code"] for item in payload(result)["errors"]})


if __name__ == "__main__":
    unittest.main()
