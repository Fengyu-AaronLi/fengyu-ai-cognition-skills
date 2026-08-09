#!/usr/bin/env python3
"""R72 red contracts for an add-only R66-R71 red-evidence ledger.

The historical Markdown reports are useful to a human, but they are not a
closed evidence set until one verifier binds the original red-test bytes, the
pre-repair environment/output record, and every evidence artifact.  The first
seven records below are the immutable prefix.  Later rounds may append records
but may not rewrite or reorder this prefix.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evals" / "red-evidence-manifest.json"
TEST_MANIFEST = ROOT / "evals" / "test-generation-manifest.json"
VERIFIER = ROOT / "scripts" / "verify_red_evidence_manifest.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


EXPECTED_PREFIX = (
    {
        "evidence_id": "r66-post-freeze-runtime-and-state",
        "round_id": "R66",
        "evidence": (
            "evals/raw/v66-red/post-freeze-runtime-and-state.md",
            "53ba737881b01e4447fd94f4fba090c791159a2ae21acd97a298b8306a1efc15",
        ),
        "tests": (
            (
                "tests/test_v66_runtime_safety.py",
                "4c13187b7b8b11a0a1acb6a85c940338e18f6a5ae32827644decc29910ab17e4",
            ),
            (
                "tests/test_v66_state_preference.py",
                "a4123a14f8557e6976f2bfb1431576055a7b1af1ff580a927b18f4b94a77bd4e",
            ),
        ),
        "environment_status": "recorded",
        "environment_markers": (
            "Captured: 2026-08-06 Australia/Sydney",
            "Environment: macOS Darwin 25.5.0 arm64; Python 3.14.4",
        ),
        "output_markers": (
            "Ran 8 tests in 0.097s",
            "FAILED (failures=20)",
            "Ran 3 tests in 1.962s",
            "FAILED (failures=6)",
        ),
    },
    {
        "evidence_id": "r67-runtime-adversarial-second-pass",
        "round_id": "R67",
        "evidence": (
            "evals/raw/v67-red/runtime-adversarial-second-pass.md",
            "3df1a8fdc9a33e994c0d26543d2d99363c89c563a59227a3e258cdd92d287ab4",
        ),
        "tests": (
            (
                "tests/test_v67_runtime_adversarial.py",
                "d2e752cc16954618822fa257c537d040ceae349ca114ceb00493b268113ac8a2",
            ),
        ),
        "environment_status": "recorded",
        "environment_markers": (
            "Python: `3.14.4`",
            "Platform: `Darwin 25.5.0 arm64`",
            "Runtime SHA-256 before repair: `fe48ca0f912f7be4efe3c2d3c4543160e2a95e4bd2193a9a7999e1c348eaffe0`",
        ),
        "output_markers": (
            "Ran 13 tests in 3.319s",
            "FAILED (failures=18)",
        ),
    },
    {
        "evidence_id": "r68-regression-dependency-closure",
        "round_id": "R68",
        "evidence": (
            "evals/raw/v68-red/regression-dependency-closure.md",
            "d4b14d2cb251dc60956c958c6c462a8d6fd9aa9c199fbd9daecf661f3f08b936",
        ),
        "tests": (
            (
                "tests/test_v68_dependency_inventory.py",
                "978105721f1ac674ccf2478acde6fb455e5b20ef2567706e2b908cecd9ee87d3",
            ),
        ),
        "environment_status": "recorded",
        "environment_markers": (
            "Python: `3.14.4`",
            "Platform: `Darwin 25.5.0 arm64`",
        ),
        "output_markers": (
            "Ran 10 tests in 0.207s",
            "FAILED (failures=11)",
        ),
    },
    {
        "evidence_id": "r69-scope-and-language-matrix",
        "round_id": "R69",
        "evidence": (
            "evals/raw/v69-red/scope-and-language-matrix.md",
            "5ac326d7b8381ac50f834e0cd7aa95272208ba175490dbbdf1be7ac7a3638b69",
        ),
        "tests": (
            (
                "tests/test_v69_scope_language_matrix.py",
                "d97bd19bfe32c37b1575e754804fb2c83fc0d13d1019399a1cea6d9aa82955df",
            ),
        ),
        "environment_status": "recorded",
        "environment_markers": (
            "Python: `3.14.4`",
            "Platform: `Darwin 25.5.0 arm64`",
        ),
        "output_markers": (
            "Ran 11 tests in 1.187s",
            "FAILED (failures=12)",
        ),
    },
    {
        "evidence_id": "r70-runtime-semantic-fuzz",
        "round_id": "R70",
        "evidence": (
            "evals/raw/v70-red/runtime-semantic-fuzz.md",
            "37a1dffb03309cce60758f8ca2153360959b26a0c887b0fbef389e758e9553e8",
        ),
        "tests": (
            (
                "tests/test_v70_runtime_semantic_fuzz.py",
                "438674d1aa1812c648adb7bd48fd24be76c777f0def1cfcf3a4f8cc390445fd3",
            ),
        ),
        "environment_status": "partial",
        "environment_markers": ("against the post-R69 runtime",),
        "output_markers": (
            "Ran 7 tests in 0.334s",
            "FAILED (failures=16)",
        ),
    },
    {
        "evidence_id": "r70-source-validation-mutable-state",
        "round_id": "R70",
        "evidence": (
            "evals/raw/v70-red/source-validation-mutable-state.md",
            "c08063c4daec9b8bd8f170b208c4811871b1fa1ec6f056a818c43ea338f41463",
        ),
        "tests": (
            (
                "tests/test_v70_source_validation_dependency.py",
                "d3efc7f1de2f5aca572efcf7a3d50bca474c36eff6d0b7ef70694cf1b4cb82e5",
            ),
        ),
        "environment_status": "partial",
        "environment_markers": (
            "Date: 2026-08-06 Australia/Sydney",
            "Runtime: local `python3`",
        ),
        "output_markers": (
            "Ran 2 tests in 0.074s",
            "FAILED (failures=2)",
        ),
    },
    {
        "evidence_id": "r71-regression-dependency-closed-world",
        "round_id": "R71",
        "evidence": (
            "evals/raw/v71-red/regression-dependency-closed-world.md",
            "8eb54f9df2ff0a7092c49bf943a25b242cee3d1498d0efb8e87a0670b3a86216",
        ),
        "tests": (
            (
                "tests/test_v71_regression_dependency_closed_world.py",
                "aeea94f7d4e1e428d83879b28cf93a7f7dca529896691ce53e8e289a1d4f80da",
            ),
        ),
        "environment_status": "partial",
        "environment_markers": ("This is local red-stage evidence.",),
        "output_markers": (
            "Ran 1 test in 0.020s",
            "FAILED (failures=1)",
        ),
    },
)


def run_verifier(root: Path, manifest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--root",
            str(root),
            "--manifest",
            str(manifest),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def records_by_id(payload: dict) -> dict[str, dict]:
    records = payload.get("records")
    if not isinstance(records, list):
        return {}
    return {
        item.get("evidence_id"): item
        for item in records
        if isinstance(item, dict) and isinstance(item.get("evidence_id"), str)
    }


class RedEvidenceManifestClosureTests(unittest.TestCase):
    def require_current_contract(self) -> dict:
        self.assertTrue(MANIFEST.is_file(), "R66-R71 need one add-only red-evidence manifest")
        self.assertTrue(VERIFIER.is_file(), "the red-evidence manifest needs a verifier")
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual("1.0", payload.get("schema_version"))
        self.assertIs(True, payload.get("append_only"))
        return payload

    def test_current_prefix_binds_original_evidence_tests_environment_and_output(self) -> None:
        payload = self.require_current_contract()
        records = payload.get("records")
        self.assertIsInstance(records, list)
        self.assertGreaterEqual(len(records), len(EXPECTED_PREFIX))
        expected_ids = [item["evidence_id"] for item in EXPECTED_PREFIX]
        self.assertEqual(expected_ids, [item.get("evidence_id") for item in records[:7]])
        observed = records_by_id(payload)

        for expected in EXPECTED_PREFIX:
            with self.subTest(evidence_id=expected["evidence_id"]):
                record = observed[expected["evidence_id"]]
                self.assertEqual(expected["round_id"], record.get("round_id"))
                evidence = record.get("evidence")
                self.assertEqual(
                    {"path": expected["evidence"][0], "sha256": expected["evidence"][1]},
                    evidence,
                )
                tests = record.get("tests")
                self.assertEqual(
                    [
                        {"path": path, "sha256": sha256}
                        for path, sha256 in expected["tests"]
                    ],
                    tests,
                )
                capture = record.get("pre_fix_capture")
                self.assertIsInstance(capture, dict)
                environment = capture.get("environment")
                output = capture.get("output")
                self.assertEqual(expected["environment_status"], environment.get("status"))
                self.assertEqual(
                    list(expected["environment_markers"]),
                    environment.get("markers"),
                )
                self.assertEqual("recorded", output.get("status"))
                self.assertEqual(list(expected["output_markers"]), output.get("markers"))

                evidence_path = ROOT / expected["evidence"][0]
                self.assertEqual(expected["evidence"][1], digest(evidence_path))
                text = evidence_path.read_text(encoding="utf-8")
                for marker in (*expected["environment_markers"], *expected["output_markers"]):
                    self.assertIn(marker, text)
                for test_path, test_sha256 in expected["tests"]:
                    current_sha256 = digest(ROOT / test_path)
                    if current_sha256 == test_sha256:
                        continue
                    test_manifest = json.loads(TEST_MANIFEST.read_text(encoding="utf-8"))
                    test_record = next(
                        item
                        for item in test_manifest["files"]
                        if item.get("path") == test_path
                    )
                    migration_hashes = {
                        value
                        for entry in test_record.get("migration_history", [])
                        for value in (entry.get("from_sha256"), entry.get("to_sha256"))
                    }
                    self.assertIn(test_sha256, migration_hashes)
                    self.assertEqual(current_sha256, test_record.get("sha256"))

        sealed = payload.get("sealed_prefix")
        self.assertIsInstance(sealed, dict)
        self.assertEqual(7, sealed.get("record_count"))
        self.assertEqual(
            hashlib.sha256(canonical_json(records[:7])).hexdigest(),
            sealed.get("sha256"),
        )

        result = run_verifier(ROOT, MANIFEST)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        verified = json.loads(result.stdout)
        self.assertTrue(verified.get("valid"))
        self.assertEqual(len(records), verified.get("record_count"))
        self.assertEqual(7, verified.get("sealed_record_count"))

    def copied_fixture(self, target_root: Path) -> Path:
        payload = self.require_current_contract()
        manifest = target_root / "evals" / "red-evidence-manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_bytes(canonical_json(payload))
        current_test_manifest = json.loads(TEST_MANIFEST.read_text(encoding="utf-8"))
        required_test_paths = {
            binding["path"]
            for record in payload["records"]
            for binding in record["tests"]
        }
        test_records = [
            record
            for record in current_test_manifest["files"]
            if record.get("path") in required_test_paths
        ]
        fixture_test_manifest = {
            "schema_version": "1.0",
            "files": test_records,
            "generation_rules": [],
            "support_files": [],
        }
        test_manifest_target = target_root / "evals" / "test-generation-manifest.json"
        test_manifest_target.write_bytes(canonical_json(fixture_test_manifest))
        for record in payload["records"]:
            bindings = [record["evidence"], *record["tests"]]
            for binding in bindings:
                source = ROOT / binding["path"]
                target = target_root / binding["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copyfile(source, target)
        for record in test_records:
            for entry in record.get("migration_history", []):
                receipt_source = ROOT / entry["receipt_path"]
                receipt_target = target_root / entry["receipt_path"]
                receipt_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(receipt_source, receipt_target)
                receipt = json.loads(receipt_source.read_text(encoding="utf-8"))
                for binding in [*receipt["evidence"], *receipt["replacement_tests"]]:
                    source = ROOT / binding["path"]
                    target = target_root / binding["path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        shutil.copyfile(source, target)
        return manifest

    def test_verifier_fails_closed_when_bound_evidence_or_test_is_missing(self) -> None:
        for binding_kind in ("evidence", "test"):
            with self.subTest(binding_kind=binding_kind):
                with tempfile.TemporaryDirectory(prefix="identity-v72-red-ledger-") as temp:
                    root = Path(temp)
                    manifest = self.copied_fixture(root)
                    payload = json.loads(manifest.read_text(encoding="utf-8"))
                    binding = (
                        payload["records"][0]["evidence"]
                        if binding_kind == "evidence"
                        else payload["records"][0]["tests"][0]
                    )
                    (root / binding["path"]).unlink()
                    result = run_verifier(root, manifest)
                    self.assertEqual(3, result.returncode, result.stdout + result.stderr)
                    self.assertIn("red_evidence_artifact_missing", result.stdout)

    def test_verifier_rejects_hash_drift_and_removal_from_sealed_prefix(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v72-red-ledger-") as temp:
            root = Path(temp)
            manifest = self.copied_fixture(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            evidence = root / payload["records"][0]["evidence"]["path"]
            evidence.write_bytes(evidence.read_bytes() + b"\nmutated\n")
            drift = run_verifier(root, manifest)
            self.assertEqual(3, drift.returncode, drift.stdout + drift.stderr)
            self.assertIn("red_evidence_artifact_hash_mismatch", drift.stdout)

        with tempfile.TemporaryDirectory(prefix="identity-v72-red-ledger-") as temp:
            root = Path(temp)
            manifest = self.copied_fixture(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["records"].pop(2)
            manifest.write_bytes(canonical_json(payload))
            removed = run_verifier(root, manifest)
            self.assertEqual(3, removed.returncode, removed.stdout + removed.stderr)
            self.assertIn("red_evidence_sealed_prefix_invalid", removed.stdout)


if __name__ == "__main__":
    unittest.main()
