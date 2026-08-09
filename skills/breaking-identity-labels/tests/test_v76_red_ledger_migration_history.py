#!/usr/bin/env python3
"""R76 red contracts for historical red-test hashes after test migration.

A sealed red-evidence record describes the test bytes that produced the
pre-fix failure.  Those bytes must remain valid evidence after the test itself
is deliberately migrated, provided the current test-generation manifest has a
continuous, receipt-verified chain from the historical hash to the current
file.  The sealed record must not be rewritten just to follow the green test.
"""

from __future__ import annotations

import copy
import hashlib
import json
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "evals" / "red-evidence-manifest.json"
TEST_MANIFEST = ROOT / "evals" / "test-generation-manifest.json"
LEDGER_VERIFIER = ROOT / "scripts" / "verify_red_evidence_manifest.py"
CONTROLLER = ROOT / "scripts" / "run_evolution.py"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value))


def checked_in_verifier() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(LEDGER_VERIFIER),
            "--root",
            str(ROOT),
            "--manifest",
            str(LEDGER),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class HistoricalRedHashFixture:
    """One sealed record plus a two-hop, file-backed test migration chain."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.test_relative = "tests/test_v76_fixture.py"
        self.evidence_relative = "evals/raw/v76-red/fixture.md"
        self.manifest_path = root / "evals" / "test-generation-manifest.json"
        self.ledger_path = root / "evals" / "red-evidence-manifest.json"

        historical_bytes = b"raise AssertionError('pre-fix red')\n"
        midpoint_bytes = b"# migrated once\nraise AssertionError('still red')\n"
        current_bytes = b"# migrated twice\nassert True\n"
        self.historical_sha = sha256_bytes(historical_bytes)
        self.midpoint_sha = sha256_bytes(midpoint_bytes)
        self.current_sha = sha256_bytes(current_bytes)

        test_path = root / self.test_relative
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_bytes(current_bytes)

        evidence_path = root / self.evidence_relative
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            "Fixture Python: 3.14.4\nRan 1 test in 0.001s\n"
            "FAILED (failures=1)\n",
            encoding="utf-8",
        )
        self.evidence_sha = sha256_file(evidence_path)

        first_receipt = self._receipt(
            receipt_id="v76-fixture-first",
            from_sha=self.historical_sha,
            to_sha=self.midpoint_sha,
            replacement_sha=self.midpoint_sha,
        )
        second_receipt = self._receipt(
            receipt_id="v76-fixture-second",
            from_sha=self.midpoint_sha,
            to_sha=self.current_sha,
            replacement_sha=self.current_sha,
        )
        self.first_receipt_path = (
            root / "evals" / "test-migrations" / "v76-fixture-first.json"
        )
        self.second_receipt_path = (
            root / "evals" / "test-migrations" / "v76-fixture-second.json"
        )
        write_json(self.first_receipt_path, first_receipt)
        write_json(self.second_receipt_path, second_receipt)

        self.test_manifest = {
            "schema_version": "1.0",
            "files": [
                {
                    "generation": "v76",
                    "path": self.test_relative,
                    "sha256": self.current_sha,
                    "migration_history": [
                        self._history_entry(
                            self.historical_sha,
                            self.midpoint_sha,
                            self.first_receipt_path,
                        ),
                        self._history_entry(
                            self.midpoint_sha,
                            self.current_sha,
                            self.second_receipt_path,
                        ),
                    ],
                }
            ],
            "generation_rules": [
                {
                    "generation": "v76",
                    "minimum": 1,
                    "pattern": "tests/test_v76_*.py",
                }
            ],
        }
        write_json(self.manifest_path, self.test_manifest)

        self.record = {
            "evidence_id": "r76-fixture-historical-red-hash",
            "round_id": "R76",
            "evidence": {
                "path": self.evidence_relative,
                "sha256": self.evidence_sha,
            },
            "tests": [
                {"path": self.test_relative, "sha256": self.historical_sha}
            ],
            "pre_fix_capture": {
                "environment": {
                    "status": "recorded",
                    "markers": ["Fixture Python: 3.14.4"],
                },
                "output": {
                    "status": "recorded",
                    "markers": ["FAILED (failures=1)"],
                },
            },
        }
        self.ledger = {
            "schema_version": "1.0",
            "append_only": True,
            "records": [self.record],
            "sealed_prefix": {"record_count": 1, "sha256": ""},
        }
        self.reseal()

    def _receipt(
        self,
        *,
        receipt_id: str,
        from_sha: str,
        to_sha: str,
        replacement_sha: str,
    ) -> dict:
        return {
            "schema_version": "1.0",
            "receipt_id": receipt_id,
            "test_path": self.test_relative,
            "from_sha256": from_sha,
            "to_sha256": to_sha,
            "reason": "Fixture migration preserves the red contract while adapting its harness.",
            "replacement_tests": [
                {"path": self.test_relative, "sha256": replacement_sha}
            ],
            "evidence": [
                {"path": self.evidence_relative, "sha256": self.evidence_sha}
            ],
            "reviewed_by": "r76-isolated-fixture",
            "reviewed_at": "2026-08-07T12:00:00+10:00",
        }

    def _history_entry(self, from_sha: str, to_sha: str, receipt: Path) -> dict:
        return {
            "from_sha256": from_sha,
            "to_sha256": to_sha,
            "receipt_path": receipt.relative_to(self.root).as_posix(),
            "receipt_sha256": sha256_file(receipt),
        }

    def reseal(self) -> None:
        sealed_sha = sha256_bytes(canonical_json(self.ledger["records"][:1]))
        self.ledger["sealed_prefix"]["sha256"] = sealed_sha
        write_json(self.ledger_path, self.ledger)


class RedLedgerMigrationHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verifier_module = runpy.run_path(str(LEDGER_VERIFIER))
        cls.controller_module = runpy.run_path(str(CONTROLLER))

    def verify_fixture(self, fixture: HistoricalRedHashFixture) -> dict:
        verify = self.verifier_module["verify"]
        verify.__globals__["TRUSTED_PREFIX_COUNT"] = 1
        verify.__globals__["TRUSTED_PREFIX_SHA256"] = fixture.ledger[
            "sealed_prefix"
        ]["sha256"]
        return verify(fixture.root, fixture.ledger_path)

    def test_checked_in_r67_red_hash_survives_verified_v74_test_migration(self) -> None:
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        manifest = json.loads(TEST_MANIFEST.read_text(encoding="utf-8"))
        migration_errors = self.controller_module[
            "validate_manifest_migration_history"
        ](ROOT, manifest)
        self.assertEqual([], migration_errors)

        record = next(
            item
            for item in ledger["records"]
            if item["evidence_id"] == "r67-runtime-adversarial-second-pass"
        )
        test_binding = record["tests"][0]
        test_record = next(
            item for item in manifest["files"] if item["path"] == test_binding["path"]
        )
        history = test_record["migration_history"]
        self.assertEqual(test_binding["sha256"], history[0]["from_sha256"])
        self.assertEqual(test_record["sha256"], history[-1]["to_sha256"])
        self.assertEqual(test_record["sha256"], sha256_file(ROOT / test_record["path"]))
        self.assertNotEqual(test_binding["sha256"], test_record["sha256"])

        result = checked_in_verifier()

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])

    def test_isolated_continuous_verified_history_accepts_historical_red_hash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v76-red-history-") as temp:
            fixture = HistoricalRedHashFixture(Path(temp))

            result = self.verify_fixture(fixture)

            self.assertTrue(result["valid"])
            self.assertEqual(1, result["record_count"])

    def test_hash_outside_current_or_migration_chain_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v76-red-history-") as temp:
            fixture = HistoricalRedHashFixture(Path(temp))
            fixture.record["tests"][0]["sha256"] = sha256_bytes(
                b"not part of any migration"
            )
            fixture.reseal()

            error = self.verifier_module["RedLedgerError"]
            with self.assertRaises(error):
                self.verify_fixture(fixture)

    def test_receipt_semantic_drift_is_not_a_verified_migration(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v76-red-history-") as temp:
            fixture = HistoricalRedHashFixture(Path(temp))
            receipt = json.loads(fixture.first_receipt_path.read_text(encoding="utf-8"))
            receipt["test_path"] = "tests/test_v76_another_fixture.py"
            write_json(fixture.first_receipt_path, receipt)
            fixture.test_manifest["files"][0]["migration_history"][0][
                "receipt_sha256"
            ] = sha256_file(fixture.first_receipt_path)
            write_json(fixture.manifest_path, fixture.test_manifest)

            error = self.verifier_module["RedLedgerError"]
            with self.assertRaises(error):
                self.verify_fixture(fixture)

    def test_evidence_file_drift_remains_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v76-red-history-") as temp:
            fixture = HistoricalRedHashFixture(Path(temp))
            evidence = fixture.root / fixture.evidence_relative
            evidence.write_bytes(evidence.read_bytes() + b"drift\n")

            error = self.verifier_module["RedLedgerError"]
            with self.assertRaisesRegex(error, "red_evidence_artifact_hash_mismatch"):
                self.verify_fixture(fixture)


if __name__ == "__main__":
    unittest.main()
