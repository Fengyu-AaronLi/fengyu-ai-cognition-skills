from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "evals" / "runtime" / "run_runtime_evals.py"
MANIFEST = ROOT / "evals" / "suite-manifest.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_runner():
    spec = importlib.util.spec_from_file_location("suite_bound_runtime_runner", RUNNER)
    if spec is None or spec.loader is None:
        raise AssertionError("runner cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SuiteManifestContract(unittest.TestCase):
    def test_runner_has_one_manifest_source_of_truth(self) -> None:
        self.assertTrue(MANIFEST.is_file(), "evals/suite-manifest.json is missing")
        source = RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("CASE_EXPECTATIONS", source)
        module = load_runner()
        suite = module.load_suite_manifest(MANIFEST, ROOT)
        self.assertEqual(["DPBP-001", "DPBP-002", "DPBP-003", "DPBP-004"], [item["case_id"] for item in suite["cases"]])

    def test_manifest_binds_every_fixture_by_hash(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for case in manifest["partitions"]["regression"]:
            envelope = ROOT / case["envelope_file"]
            self.assertEqual(case["envelope_sha256"], sha256_file(envelope))
            if case["spec_file"] is None:
                self.assertIsNone(case["spec_sha256"])
            else:
                spec = ROOT / case["spec_file"]
                self.assertEqual(case["spec_sha256"], sha256_file(spec))

    def test_loader_fails_closed_when_a_fixture_hash_changes(self) -> None:
        module = load_runner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = root / "input.json"
            fixture.write_text("{}\n", encoding="utf-8")
            manifest = {
                "schema_version": "1.0",
                "suite_id": "tampered",
                "suite_version": "1",
                "partitions": {
                    "regression": [{
                        "case_id": "X",
                        "envelope_file": "input.json",
                        "envelope_sha256": "0" * 64,
                        "spec_file": None,
                        "spec_sha256": None,
                        "expected": {"mode": "execute", "rule": "clear_execution", "resources": [], "requires_spec": False},
                    }],
                    "sealed_holdout": [],
                },
                "policy": {"max_iterations": 3, "saturation_window": 2, "minimum_improvement": 0.05, "required_roles": ["author", "reproducer", "reviewer"]},
            }
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash"):
                module.load_suite_manifest(path, root)

    def test_report_carries_suite_identity_and_manifest_hash(self) -> None:
        module = load_runner()
        suite = module.load_suite_manifest(MANIFEST, ROOT)
        report = module.build_report(
            skill_root=ROOT,
            suite=suite,
            repetitions=1,
        )
        self.assertEqual(suite["suite_id"], report["suite"]["suite_id"])
        self.assertEqual(suite["suite_version"], report["suite"]["suite_version"])
        self.assertEqual(sha256_file(MANIFEST), report["suite"]["manifest_sha256"])


if __name__ == "__main__":
    unittest.main()
