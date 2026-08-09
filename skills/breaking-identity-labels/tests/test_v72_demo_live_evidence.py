#!/usr/bin/env python3
"""R72 red contracts for demo writes and live-evidence provenance."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEMO_BUILDER = ROOT / "scripts" / "build_demo.py"
LIVE_MANIFEST = ROOT / "evals" / "live-e2e-manifest.json"
LIVE_MANIFEST_SCHEMA = ROOT / "evals" / "schemas" / "live-e2e-manifest.schema.json"
LIVE_RUN_SCHEMA = ROOT / "evals" / "schemas" / "live-e2e-run.schema.json"
V68_WORKFLOW = ROOT / "workflows" / "v68-final-release.json"
DEMO_ARTIFACTS = {
    "case.json",
    "events.jsonl",
    "events.head.json",
    "report.md",
    "run-manifest.json",
}
EVIDENCE_MODES = {
    "historical_analysis_replay",
    "fresh_candidate_agent_run",
}


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value


def binding_matches_file(base: Path, binding: object) -> bool:
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
        return False
    relative = binding.get("path")
    expected = binding.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected, str):
        return False
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or len(expected) != 64:
        return False
    artifact = base / candidate
    if artifact.is_symlink() or not artifact.is_file():
        return False
    return hashlib.sha256(artifact.read_bytes()).hexdigest() == expected


class DemoWriteBoundaryRedTests(unittest.TestCase):
    def run_builder(self, output_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(DEMO_BUILDER),
                "--output-dir",
                str(output_dir),
                "--clock",
                "2026-08-07T10:00:00Z",
                *extra,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_default_rejects_an_already_existing_output_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v72-demo-existing-dir-") as temporary:
            output_dir = Path(temporary) / "demo"
            output_dir.mkdir()

            result = self.run_builder(output_dir)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual(list(output_dir.iterdir()), [])

    def test_default_rejection_does_not_overwrite_an_existing_target_artifact(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v72-demo-existing-artifact-") as temporary:
            output_dir = Path(temporary) / "demo"
            output_dir.mkdir()
            frozen = output_dir / "report.md"
            original = b"user-owned-report\n"
            frozen.write_bytes(original)

            result = self.run_builder(output_dir)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual(frozen.read_bytes(), original)
            self.assertEqual({path.name for path in output_dir.iterdir()}, {"report.md"})

    def test_explicit_force_rebuilds_known_targets_but_preserves_unknown_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v72-demo-force-") as temporary:
            output_dir = Path(temporary) / "demo"
            output_dir.mkdir()
            sentinel = output_dir / "user-notes.txt"
            sentinel_bytes = b"keep this unknown file byte-for-byte\n"
            sentinel.write_bytes(sentinel_bytes)

            result = self.run_builder(output_dir, "--force")

            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertEqual(sentinel.read_bytes(), sentinel_bytes)
            self.assertTrue(DEMO_ARTIFACTS.issubset({path.name for path in output_dir.iterdir()}))


class LiveEvidenceProvenanceRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = read_json(LIVE_MANIFEST)
        cls.manifest_schema = read_json(LIVE_MANIFEST_SCHEMA)
        cls.run_schema = read_json(LIVE_RUN_SCHEMA)

    def test_checked_manifest_declares_one_truthful_evidence_mode(self) -> None:
        self.assertIn(self.manifest.get("evidence_mode"), EVIDENCE_MODES)

    def test_checked_manifest_binds_a_named_candidate_to_skill_and_runtime(self) -> None:
        candidate = self.manifest.get("candidate")
        self.assertIsInstance(candidate, dict)
        self.assertEqual(
            set(candidate),
            {"candidate_id", "skill_sha256", "runtime_sha256"},
        )
        self.assertIsInstance(candidate["candidate_id"], str)
        self.assertTrue(candidate["candidate_id"].strip())
        self.assertEqual(
            candidate["skill_sha256"],
            self.manifest["bindings"]["skill"]["sha256"],
        )
        self.assertEqual(
            candidate["runtime_sha256"],
            self.manifest["bindings"]["runtime"]["sha256"],
        )

    def test_r64_analysis_bundle_can_only_be_declared_as_historical_replay(self) -> None:
        run_paths = [item["run"]["path"] for item in self.manifest.get("cases", [])]
        if any("current-live-e2e-r64/" in path for path in run_paths):
            self.assertEqual(
                self.manifest.get("evidence_mode"),
                "historical_analysis_replay",
            )
            self.assertEqual(
                self.manifest.get("run_type"),
                "historical_analysis_runtime_replay",
            )
            self.assertEqual(
                self.manifest.get("evidence_level"),
                "historical_analysis_replay_sample",
            )
        else:
            self.assertEqual(
                self.manifest.get("evidence_mode"),
                "fresh_candidate_agent_run",
            )

    def test_every_run_binds_the_candidate_and_its_actual_analysis_origin(self) -> None:
        candidate = self.manifest.get("candidate")
        candidate_id = candidate.get("candidate_id") if isinstance(candidate, dict) else None
        mode = self.manifest.get("evidence_mode")
        failures: list[str] = []
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            failures.append("manifest:candidate_id")
        if mode not in EVIDENCE_MODES:
            failures.append("manifest:evidence_mode")
        for item in self.manifest.get("cases", []):
            case_id = item.get("case_id", "unknown")
            run_path = ROOT / item["run"]["path"]
            run = read_json(run_path)
            if run.get("candidate_id") != candidate_id:
                failures.append(f"{case_id}:candidate_id")
            if run.get("evidence_mode") != mode:
                failures.append(f"{case_id}:evidence_mode")

            if mode == "fresh_candidate_agent_run":
                artifacts = run.get("artifacts", {})
                for name in ("agent_request", "agent_response"):
                    binding = artifacts.get(name)
                    if not binding_matches_file(run_path.parent, binding):
                        failures.append(f"{case_id}:{name}")
            elif mode == "historical_analysis_replay" and run.get("route_mode") == "deconstruct":
                provenance = run.get("analysis_provenance")
                analysis = run.get("artifacts", {}).get("model_analysis", {})
                if not isinstance(provenance, dict):
                    failures.append(f"{case_id}:analysis_provenance")
                    continue
                if provenance.get("mode") != "historical_analysis_replay":
                    failures.append(f"{case_id}:analysis_provenance_mode")
                if provenance.get("source_candidate_id") in {None, "", candidate_id}:
                    failures.append(f"{case_id}:source_candidate_id")
                if provenance.get("source_analysis_sha256") != analysis.get("sha256"):
                    failures.append(f"{case_id}:source_analysis_sha256")
        self.assertEqual(failures, [])

    def test_schemas_require_candidate_mode_and_fresh_request_response_bindings(self) -> None:
        self.assertTrue(
            {"candidate", "evidence_mode"}.issubset(set(self.manifest_schema.get("required", [])))
        )
        self.assertTrue(
            {"candidate_id", "evidence_mode"}.issubset(set(self.run_schema.get("required", [])))
        )
        run_schema_text = json.dumps(self.run_schema, ensure_ascii=False, sort_keys=True)
        for token in (
            "historical_analysis_replay",
            "fresh_candidate_agent_run",
            "agent_request",
            "agent_response",
            "analysis_provenance",
        ):
            self.assertIn(token, run_schema_text)


class WorkflowInputBindingRedTests(unittest.TestCase):
    def test_v68_package_equivalence_binds_the_source_package_builder(self) -> None:
        workflow = read_json(V68_WORKFLOW)
        step = next(item for item in workflow["steps"] if item["id"] == "package_equivalence")
        self.assertIn("{root}/scripts/build_package.py", step["input_files"])


if __name__ == "__main__":
    unittest.main()
