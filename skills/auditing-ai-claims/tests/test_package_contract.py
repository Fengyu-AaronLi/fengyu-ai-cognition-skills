from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
RUNTIME = SKILL_DIR / "scripts" / "claim_audit.py"
INSTALLER = SKILL_DIR / "scripts" / "install.py"


class PackageContractTests(unittest.TestCase):
    def test_required_release_files_exist(self):
        required = [
            "SKILL.md",
            "agents/openai.yaml",
            "README.md",
            "PROVENANCE.md",
            "problem-spec.md",
            "zero-threshold-prompt.md",
            "evals/cases.json",
            "evals/baseline-report.md",
            "evals/results.md",
            "examples/demo.md",
            "launch/video-brief.md",
            "scripts/claim_audit.py",
            "schemas/candidates.schema.json",
            "schemas/claim.schema.json",
            "schemas/claim-ledger.schema.json",
            "schemas/countercheck.schema.json",
            "schemas/evidence.schema.json",
            "schemas/source-receipt.schema.json",
            "schemas/source-transaction.schema.json",
            "schemas/summary.schema.json",
            "schemas/assessment.schema.json",
            "schemas/gate-report.schema.json",
            "schemas/workflow-next.schema.json",
            "templates/candidates.json",
            "templates/claim.json",
            "templates/countercheck.json",
            "templates/evidence.json",
            "templates/assessment.json",
            "templates/summary.json",
            "references/runtime-contract.md",
            "references/source-policy.md",
            "references/status-policy.md",
            "references/workflow-loop.md",
            "references/v1-prompt-spec.md",
        ]
        missing = [relative for relative in required if not (SKILL_DIR / relative).is_file()]
        self.assertEqual(missing, [])

    def test_all_json_release_files_parse(self):
        files = sorted(
            path
            for path in SKILL_DIR.rglob("*.json")
            if "live-smoke-run" not in path.parts and "runs" not in path.parts
        )
        self.assertGreaterEqual(len(files), 8)
        for path in files:
            with self.subTest(path=path.relative_to(SKILL_DIR)):
                json.loads(path.read_text(encoding="utf-8"))

    def test_skill_entrypoint_is_compact_and_trigger_only(self):
        content = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(content.splitlines()), 160)
        self.assertTrue(content.startswith("---\nname: auditing-ai-claims\n"))
        description = content.split("---", 2)[1].lower()
        for positive_trigger in ("price", "laws", "ceos", "doi"):
            self.assertIn(positive_trigger, description)
        for negative_trigger in ("creative writing", "metaphor", "personal feelings", "relationship motives"):
            self.assertIn(negative_trigger, description)
        self.assertIn("scripts/claim_audit.py", content)
        start_command = 'python3 "$RUNTIME" start --input'
        next_command = 'python3 "$RUNTIME" next --workspace'
        self.assertIn(start_command, content)
        self.assertGreater(content.find(next_command), content.find(start_command))
        self.assertIn(
            "start → next → claim_extraction → claim_assessment → claim_countercheck",
            content,
        )
        self.assertIn(
            "→ audit_summary → gate_repair → ready_to_finish → complete",
            content,
        )
        self.assertIn("`next` 是唯一进度导航", content)
        self.assertIn("`next.stage=ready_to_finish`", content)
        self.assertIn("`complete=true`", content)
        self.assertIn("references/workflow-loop.md", content)
        self.assertIn("exclude-candidate", content)
        for safe_input in (
            "--candidates-file",
            "--candidate-id",
            "claim --workspace",
            "evidence --workspace",
            "countercheck --workspace",
            "summarize --workspace",
        ):
            self.assertIn(safe_input, content)
        self.assertIn("审计未执行", content)

    def test_runtime_is_executable_and_doctor_is_healthy(self):
        self.assertTrue(os.access(RUNTIME, os.X_OK), "runtime should be directly executable")
        result = subprocess.run(
            [sys.executable, str(RUNTIME), "doctor"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["runtime_version"], "3.1.0")
        self.assertTrue(payload["standard_library_only"])

    def test_zero_threshold_prompt_is_labeled_as_fallback(self):
        prompt = (SKILL_DIR / "zero-threshold-prompt.md").read_text(encoding="utf-8")
        self.assertIn("降级", prompt)
        self.assertIn("不能冒充完整 `auditing-ai-claims` 工作台", prompt)

    def test_assessment_template_satisfies_runtime_required_fields(self):
        template = json.loads(
            (SKILL_DIR / "templates" / "assessment.json").read_text(encoding="utf-8")
        )
        self.assertTrue(template["unknowns"])
        self.assertTrue(all(item.strip() for item in template["unknowns"]))
        self.assertTrue(template["next_action"].strip())

        schema = json.loads(
            (SKILL_DIR / "schemas" / "assessment.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(schema["properties"]["unknowns"]["minItems"], 1)
        self.assertEqual(
            schema["properties"]["unknowns"]["items"]["minLength"], 1
        )
        self.assertEqual(schema["properties"]["next_action"]["minLength"], 1)

    def test_claim_template_runs_as_caller_input_and_countercheck_still_blocks_finish(self):
        template = json.loads(
            (SKILL_DIR / "templates" / "claim.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("assessment_recorded", template)
        self.assertNotIn("unknowns", template)
        self.assertNotIn("countercheck", template)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = template["input_candidates"][0]
            input_path = root / "answer.txt"
            input_path.write_text(candidate, encoding="utf-8")
            candidates_path = root / "candidates.json"
            candidates_path.write_text(
                json.dumps({"candidates": [candidate]}, ensure_ascii=False),
                encoding="utf-8",
            )
            workspace = root / "audit"

            started = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "start",
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--as-of",
                    "2026-08-06",
                    "--reason",
                    "caller claim template contract",
                    "--candidates-file",
                    str(candidates_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(started.returncode, 0, started.stderr)

            claimed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "claim",
                    "--workspace",
                    str(workspace),
                    "--file",
                    str(SKILL_DIR / "templates" / "claim.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(claimed.returncode, 0, claimed.stderr)
            ledger = json.loads(
                (workspace / "ledger.json").read_text(encoding="utf-8")
            )
            claim = ledger["claims"][0]
            self.assertFalse(claim["assessment_recorded"])
            self.assertEqual(claim["unknowns"], [])
            self.assertNotIn("countercheck", claim)

            assessed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "assess",
                    "--workspace",
                    str(workspace),
                    "--file",
                    str(SKILL_DIR / "templates" / "assessment.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(assessed.returncode, 0, assessed.stderr)
            ledger = json.loads(
                (workspace / "ledger.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("countercheck", ledger["claims"][0])

            next_result = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "next",
                    "--workspace",
                    str(workspace),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(next_result.returncode, 0, next_result.stderr)
            self.assertEqual(json.loads(next_result.stdout)["stage"], "claim_countercheck")

            summarized = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "summarize",
                    "--workspace",
                    str(workspace),
                    "--file",
                    str(SKILL_DIR / "templates" / "summary.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(summarized.returncode, 0)
            self.assertIn("countercheck", summarized.stderr.lower())

            checked = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "check",
                    "--workspace",
                    str(workspace),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(checked.returncode, 0)
            gate = json.loads(checked.stdout)
            self.assertEqual(gate["verdict"], "FAIL")
            self.assertIn(
                "COUNTERCHECK_REQUIRED",
                {error["code"] for error in gate["errors"]},
            )

    def test_installer_copies_runtime_allowlist_and_excludes_local_evidence(self):
        self.assertTrue(INSTALLER.is_file())
        with tempfile.TemporaryDirectory() as temp_dir:
            target_root = Path(temp_dir) / "skills"
            result = subprocess.run(
                [sys.executable, str(INSTALLER), "--target-root", str(target_root)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            target = target_root / "auditing-ai-claims"
            self.assertEqual(Path(payload["target"]), target.resolve())
            self.assertTrue((target / "SKILL.md").is_file())
            self.assertTrue((target / "agents" / "openai.yaml").is_file())
            self.assertTrue((target / "scripts" / "claim_audit.py").is_file())
            for relative in (
                "schemas/candidates.schema.json",
                "schemas/claim.schema.json",
                "schemas/countercheck.schema.json",
                "schemas/evidence.schema.json",
                "schemas/source-transaction.schema.json",
                "schemas/summary.schema.json",
                "templates/candidates.json",
                "templates/countercheck.json",
                "templates/summary.json",
            ):
                self.assertTrue((target / relative).is_file(), relative)
            self.assertFalse((target / "evals").exists())
            self.assertFalse((target / "tests").exists())
            self.assertFalse((target / "examples").exists())
            self.assertFalse((target / "launch").exists())
            self.assertEqual(list(target.rglob("attempt-result.json")), [])
            self.assertEqual([path for path in target.rglob("*") if path.is_symlink()], [])
            self.assertEqual(payload["source_tree_sha256"], payload["target_tree_sha256"])

            second = subprocess.run(
                [sys.executable, str(INSTALLER), "--target-root", str(target_root)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(second.returncode, 0)

    def test_openai_interface_metadata_matches_the_skill(self):
        metadata = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('display_name: "AI 主张审计"', metadata)
        self.assertIn("short_description:", metadata)
        self.assertIn('$auditing-ai-claims', metadata)
        self.assertIn("allow_implicit_invocation: true", metadata)

    def test_installer_removes_published_target_if_final_verification_fails(self):
        spec = importlib.util.spec_from_file_location(
            "auditing_ai_claims_installer_under_test", INSTALLER
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)

        with tempfile.TemporaryDirectory() as temp_dir:
            target_root = Path(temp_dir) / "skills"
            target = target_root / "auditing-ai-claims"
            lock = target_root / ".auditing-ai-claims.install.lock"
            expected_target = target.resolve(strict=False)
            original_tree_sha256 = installer._tree_sha256

            def fail_only_after_publish(root, relative_paths, *, require_exact=False):
                result = original_tree_sha256(
                    root, relative_paths, require_exact=require_exact
                )
                if root.resolve(strict=False) == expected_target:
                    return "0" * 64
                return result

            installer._tree_sha256 = fail_only_after_publish
            with self.assertRaises(installer.InstallError):
                installer.install(target_root)

            self.assertFalse(target.exists() or target.is_symlink())
            self.assertFalse(lock.exists() or lock.is_symlink())
            self.assertEqual(
                list(target_root.glob(".auditing-ai-claims.staging-*")), []
            )


if __name__ == "__main__":
    unittest.main()
