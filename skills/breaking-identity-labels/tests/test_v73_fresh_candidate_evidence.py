#!/usr/bin/env python3
"""R73 red contracts separating historical replay from fresh candidate evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_MANIFEST = ROOT / "evals" / "live-e2e-manifest.json"
FRESH_MANIFEST = ROOT / "evals" / "fresh-candidate-e2e-manifest.json"
WORKFLOW = ROOT / "workflows" / "v68-final-release.json"
VERIFIER = ROOT / "scripts" / "verify_live_e2e.py"
CASE_IDS = {
    "C01-mbti-capability-verdict",
    "C02-attachment-side-taking",
    "C03-formal-adhd-diagnosis",
    "C04-stable-preference-control",
}
DECONSTRUCT_CASES = CASE_IDS - {"C04-stable-preference-control"}


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bound_file(base: Path, binding: object) -> Path:
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
        raise AssertionError(f"invalid binding: {binding!r}")
    relative = binding["path"]
    if not isinstance(relative, str):
        raise AssertionError("binding path is not text")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise AssertionError(f"unsafe binding path: {relative}")
    path = base / candidate
    if path.is_symlink() or not path.is_file():
        raise AssertionError(f"missing bound file: {path}")
    if sha256(path) != binding["sha256"]:
        raise AssertionError(f"hash mismatch: {path}")
    return path


class FreshCandidateEvidenceRedTests(unittest.TestCase):
    def test_historical_replay_is_retained_and_a_separate_fresh_manifest_exists(self) -> None:
        historical = read_json(HISTORICAL_MANIFEST)
        self.assertEqual(historical.get("evidence_mode"), "historical_analysis_replay")
        self.assertEqual(historical.get("run_type"), "historical_analysis_runtime_replay")
        self.assertTrue(FRESH_MANIFEST.is_file(), "missing separate fresh-candidate manifest")
        if not FRESH_MANIFEST.is_file():
            return

        fresh = read_json(FRESH_MANIFEST)
        self.assertEqual(fresh.get("evidence_mode"), "fresh_candidate_agent_run")
        self.assertEqual(fresh.get("run_type"), "fresh_candidate_model_runtime_composition")
        self.assertEqual(fresh.get("evidence_level"), "fresh_candidate_model_runtime_sample")
        self.assertNotEqual(fresh.get("candidate"), historical.get("candidate"))
        self.assertEqual(fresh["candidate"]["skill_sha256"], sha256(ROOT / "SKILL.md"))
        self.assertEqual(
            fresh["candidate"]["runtime_sha256"],
            sha256(ROOT / "scripts" / "identity_label_case.py"),
        )
        run_paths = [item["run"]["path"] for item in fresh.get("cases", [])]
        self.assertEqual({item.get("case_id") for item in fresh.get("cases", [])}, CASE_IDS)
        self.assertFalse(any("current-live-e2e-r64/" in path for path in run_paths))
        self.assertFalse(any("examples/real-run/" in path or "generated-demo/" in path for path in run_paths))

    def test_fresh_runs_bind_agent_exchange_real_outputs_and_runtime_chain(self) -> None:
        self.assertTrue(FRESH_MANIFEST.is_file(), "missing separate fresh-candidate manifest")
        if not FRESH_MANIFEST.is_file():
            return
        fresh = read_json(FRESH_MANIFEST)
        candidate = fresh["candidate"]
        runner_tasks: set[str] = set()

        for entry in fresh["cases"]:
            case_id = entry["case_id"]
            run_path = bound_file(ROOT, entry["run"])
            run = read_json(run_path)
            self.assertEqual(run.get("candidate_id"), candidate["candidate_id"])
            self.assertEqual(run.get("evidence_mode"), "fresh_candidate_agent_run")
            runner_task = run.get("orchestration_task_id")
            self.assertIsInstance(runner_task, str)
            self.assertTrue(runner_task.startswith("/root/"))
            self.assertNotIn(runner_task, runner_tasks)
            runner_tasks.add(runner_task)

            artifacts = run.get("artifacts", {})
            request_path = bound_file(run_path.parent, artifacts.get("agent_request"))
            response_path = bound_file(run_path.parent, artifacts.get("agent_response"))
            input_path = bound_file(run_path.parent, artifacts.get("input"))
            request = read_json(request_path)
            response = read_json(response_path)

            self.assertEqual(request.get("candidate_id"), candidate["candidate_id"])
            self.assertEqual(request.get("case_id"), case_id)
            self.assertEqual(request.get("skill_sha256"), candidate["skill_sha256"])
            self.assertEqual(request.get("runtime_sha256"), candidate["runtime_sha256"])
            self.assertEqual(request.get("input_sha256"), sha256(input_path))

            self.assertEqual(response.get("candidate_id"), candidate["candidate_id"])
            self.assertEqual(response.get("case_id"), case_id)
            self.assertEqual(response.get("orchestration_task_id"), runner_task)
            if case_id in DECONSTRUCT_CASES:
                output_path = bound_file(run_path.parent, artifacts.get("model_analysis"))
                self.assertEqual(response.get("output_kind"), "structured_analysis")
            else:
                output_path = bound_file(run_path.parent, artifacts.get("delivered_output"))
                self.assertEqual(response.get("output_kind"), "preference_acknowledgement")
            self.assertEqual(response.get("output_sha256"), sha256(output_path))

            for runtime_artifact in ("scaffold", "validate", "report", "delivered_output"):
                bound_file(run_path.parent, artifacts.get(runtime_artifact))
            if case_id in DECONSTRUCT_CASES:
                bound_file(run_path.parent, artifacts.get("case"))

        review_path = bound_file(ROOT, fresh["review"])
        review = read_json(review_path)
        self.assertTrue(review.get("independent_from_runners"))
        self.assertNotIn(review.get("reviewer_task"), runner_tasks)
        self.assertEqual({item.get("case_id") for item in review.get("results", [])}, CASE_IDS)

        verified = subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                "--root",
                str(ROOT),
                "--manifest",
                str(FRESH_MANIFEST),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(verified.returncode, 0, verified.stderr or verified.stdout)

    def test_release_workflow_verifies_historical_and_fresh_evidence_as_distinct_nodes(self) -> None:
        workflow = read_json(WORKFLOW)
        steps = {item["id"]: item for item in workflow["steps"]}
        self.assertTrue("live_e2e_verify" in steps, "missing historical replay node")
        self.assertTrue(
            "fresh_candidate_live_e2e_verify" in steps,
            "missing distinct fresh-candidate verification node",
        )
        if "fresh_candidate_live_e2e_verify" not in steps:
            return

        historical = steps["live_e2e_verify"]
        fresh = steps["fresh_candidate_live_e2e_verify"]
        self.assertIn("{root}/evals/live-e2e-manifest.json", historical.get("argv", []))
        self.assertIn("{root}/evals/fresh-candidate-e2e-manifest.json", fresh.get("argv", []))
        self.assertIn("live_e2e_verify", fresh.get("depends_on", []))
        self.assertIn("fresh_candidate_live_e2e_verify", steps["package_build"].get("depends_on", []))
        self.assertIn("evals/fresh-candidate-e2e-manifest.json", fresh.get("input_files", []))

        if FRESH_MANIFEST.is_file():
            manifest = read_json(FRESH_MANIFEST)
            expected_inputs = {
                "scripts/verify_live_e2e.py",
                "evals/schemas/live-e2e-manifest.schema.json",
                "evals/schemas/live-e2e-run.schema.json",
                "evals/fresh-candidate-e2e-manifest.json",
                *(item["run"]["path"] for item in manifest["cases"]),
                manifest["review"]["path"],
            }
            self.assertTrue(expected_inputs.issubset(set(fresh.get("input_files", []))))

        for step_id in ("demo_build", "demo_verify"):
            description = steps[step_id].get("description", "").lower()
            self.assertIn("deterministic", description)
            self.assertNotIn("model demo", description)


if __name__ == "__main__":
    unittest.main()
