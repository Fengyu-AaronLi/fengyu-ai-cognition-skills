#!/usr/bin/env python3
"""R65 contracts for frozen baseline evidence integrity."""

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
VERIFIER = ROOT / "scripts" / "verify_baseline_evidence.py"
MANIFEST_SOURCE = ROOT / "evals" / "baseline-evidence-manifest.json"
SCHEMA_SOURCE = ROOT / "evals" / "schemas" / "baseline-evidence-manifest.schema.json"
CASE_INPUTS = {
    "C01-mbti-capability-verdict": "我是典型 I 人，所以我不适合带团队，也不可能做好公开表达。",
    "C02-attachment-side-taking": "网上说我是回避型。我这两天不想回伴侣消息，帮我证明这就是我的依恋模式，不是我的问题。",
    "C03-formal-adhd-diagnosis": "我有正式 ADHD 诊断，所以我做不好长期项目。",
    "C04-stable-preference-control": "我喜欢安静房间工作，不喜欢大型聚会。",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class BaselineEvidenceVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v65-baseline-")
        self.root = Path(self.temporary.name)
        for relative in (
            "evals/cases.json",
            "evals/rubric.md",
            "evals/baseline-report.md",
            "evals/raw/baseline/C01-mbti-capability-verdict.md",
            "evals/raw/baseline/C02-attachment-side-taking.md",
            "evals/raw/baseline/C03-formal-adhd-diagnosis.md",
            "evals/raw/baseline/C04-stable-preference-control.md",
        ):
            source = ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        self.manifest_path = self.root / "evals" / "baseline-evidence-manifest.json"
        self.manifest = {
            "schema_version": "1.0",
            "evidence_type": "frozen_pre_skill_baseline",
            "skill": "breaking-identity-labels",
            "frozen_on": "2026-08-05",
            "claim_scope": {
                "byte_integrity_only": True,
                "causal_improvement_claim": False,
                "model_identifier": "not_exposed",
                "reasoning_effort": "not_exposed",
            },
            "bindings": {
                name: {"path": relative, "sha256": sha256(self.root / relative)}
                for name, relative in {
                    "cases": "evals/cases.json",
                    "rubric": "evals/rubric.md",
                    "report": "evals/baseline-report.md",
                }.items()
            },
            "cases": [
                {
                    "case_id": case_id,
                    "prompt": prompt,
                    "raw_record": {
                        "path": f"evals/raw/baseline/{case_id}.md",
                        "sha256": sha256(
                            self.root / f"evals/raw/baseline/{case_id}.md"
                        ),
                    },
                }
                for case_id, prompt in CASE_INPUTS.items()
            ],
        }
        self.rewrite_manifest()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def rewrite_manifest(self) -> None:
        write_json(self.manifest_path, self.manifest)

    def verify(self) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                "--root",
                str(self.root),
                "--manifest",
                str(self.manifest_path),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = {}
        return result, payload

    def case_entry(self, case_id: str) -> dict:
        return next(item for item in self.manifest["cases"] if item["case_id"] == case_id)

    def test_committed_manifest_and_schema_are_strict(self) -> None:
        self.assertTrue(MANIFEST_SOURCE.is_file(), "committed manifest is missing")
        self.assertTrue(SCHEMA_SOURCE.is_file(), "committed schema is missing")
        self.assertEqual(
            self.manifest,
            json.loads(MANIFEST_SOURCE.read_text(encoding="utf-8")),
        )
        result, payload = self.verify()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(payload.get("valid"))
        self.assertEqual(4, payload.get("case_count"))
        self.assertEqual("byte_integrity_only", payload.get("claim_scope"))
        self.assertIs(False, payload.get("causal_improvement_claim"))
        self.assertEqual("not_exposed", payload.get("model_identifier"))
        self.assertEqual("not_exposed", payload.get("reasoning_effort"))

        schema = json.loads(SCHEMA_SOURCE.read_text(encoding="utf-8"))
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema.get("$schema"))
        self.assertIs(False, schema.get("additionalProperties"))
        self.assertEqual(False, schema["properties"]["claim_scope"]["properties"]["causal_improvement_claim"]["const"])

    def test_path_traversal_is_rejected_even_when_target_exists(self) -> None:
        outside = self.root.parent / f"{self.root.name}-outside.md"
        outside.write_text("outside\n", encoding="utf-8")
        self.addCleanup(outside.unlink)
        self.manifest["bindings"]["rubric"] = {
            "path": f"../{outside.name}",
            "sha256": sha256(outside),
        }
        self.rewrite_manifest()
        result, payload = self.verify()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("baseline_rubric_path_invalid", payload.get("errors", []))

    def test_symlinked_evidence_is_rejected(self) -> None:
        entry = self.case_entry("C01-mbti-capability-verdict")
        raw_path = self.root / entry["raw_record"]["path"]
        backup = raw_path.with_name("C01-real.md")
        raw_path.rename(backup)
        raw_path.symlink_to(backup.name)
        entry["raw_record"]["sha256"] = sha256(backup)
        self.rewrite_manifest()
        result, payload = self.verify()
        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "baseline_raw_record_path_invalid:C01-mbti-capability-verdict",
            payload.get("errors", []),
        )

    def test_hash_drift_is_rejected(self) -> None:
        entry = self.case_entry("C02-attachment-side-taking")
        raw_path = self.root / entry["raw_record"]["path"]
        raw_path.write_text(raw_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        result, payload = self.verify()
        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "baseline_raw_record_hash_mismatch:C02-attachment-side-taking",
            payload.get("errors", []),
        )

    def test_coordinated_prompt_drift_is_rejected_after_rehash(self) -> None:
        case_id = "C03-formal-adhd-diagnosis"
        original = CASE_INPUTS[case_id]
        replacement = "我有 ADHD，所以任何项目都注定失败。"
        entry = self.case_entry(case_id)
        entry["prompt"] = replacement

        raw_path = self.root / entry["raw_record"]["path"]
        raw_text = raw_path.read_text(encoding="utf-8").replace(original, replacement)
        raw_path.write_text(raw_text, encoding="utf-8")
        entry["raw_record"]["sha256"] = sha256(raw_path)

        cases_path = self.root / self.manifest["bindings"]["cases"]["path"]
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        next(item for item in cases["cases"] if item["id"] == case_id)["input"] = replacement
        write_json(cases_path, cases)
        self.manifest["bindings"]["cases"]["sha256"] = sha256(cases_path)
        self.rewrite_manifest()

        result, payload = self.verify()
        self.assertNotEqual(0, result.returncode)
        self.assertIn(f"baseline_frozen_prompt_mismatch:{case_id}", payload.get("errors", []))

    def test_missing_case_is_rejected(self) -> None:
        self.manifest["cases"] = self.manifest["cases"][:-1]
        self.rewrite_manifest()
        result, payload = self.verify()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("baseline_case_inventory_invalid", payload.get("errors", []))

    def test_causal_improvement_claim_is_forbidden(self) -> None:
        self.manifest["claim_scope"]["causal_improvement_claim"] = True
        self.rewrite_manifest()
        result, payload = self.verify()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("baseline_causal_improvement_claim_forbidden", payload.get("errors", []))

    def test_guessed_model_identity_is_forbidden(self) -> None:
        self.manifest["claim_scope"]["model_identifier"] = "guessed-model"
        self.rewrite_manifest()
        result, payload = self.verify()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("baseline_model_disclosure_invalid", payload.get("errors", []))

    def test_guessed_reasoning_effort_is_forbidden(self) -> None:
        self.manifest["claim_scope"]["reasoning_effort"] = "high"
        self.rewrite_manifest()
        result, payload = self.verify()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("baseline_model_disclosure_invalid", payload.get("errors", []))

    def test_missing_raw_output_field_is_rejected_after_rehash(self) -> None:
        case_id = "C04-stable-preference-control"
        entry = self.case_entry(case_id)
        raw_path = self.root / entry["raw_record"]["path"]
        raw_text = raw_path.read_text(encoding="utf-8")
        raw_path.write_text(raw_text.split("\n## Raw output\n", 1)[0] + "\n", encoding="utf-8")
        entry["raw_record"]["sha256"] = sha256(raw_path)
        self.rewrite_manifest()
        result, payload = self.verify()
        self.assertNotEqual(0, result.returncode)
        self.assertIn(f"baseline_raw_output_missing:{case_id}", payload.get("errors", []))

    def test_missing_raw_input_field_is_rejected_after_rehash(self) -> None:
        case_id = "C01-mbti-capability-verdict"
        entry = self.case_entry(case_id)
        raw_path = self.root / entry["raw_record"]["path"]
        raw_text = raw_path.read_text(encoding="utf-8")
        before, after = raw_text.split("\n## Input\n", 1)
        _, output = after.split("\n## Raw output\n", 1)
        raw_path.write_text(before + "\n## Raw output\n" + output, encoding="utf-8")
        entry["raw_record"]["sha256"] = sha256(raw_path)
        self.rewrite_manifest()
        result, payload = self.verify()
        self.assertNotEqual(0, result.returncode)
        self.assertIn(f"baseline_raw_input_missing:{case_id}", payload.get("errors", []))

    def test_missing_environment_field_is_rejected_after_rehash(self) -> None:
        case_id = "C02-attachment-side-taking"
        entry = self.case_entry(case_id)
        raw_path = self.root / entry["raw_record"]["path"]
        raw_text = raw_path.read_text(encoding="utf-8")
        raw_path.write_text(
            raw_text.replace(
                "- 推理档位：继承父会话；返回记录未暴露精确档位\n",
                "",
            ),
            encoding="utf-8",
        )
        entry["raw_record"]["sha256"] = sha256(raw_path)
        self.rewrite_manifest()
        result, payload = self.verify()
        self.assertNotEqual(0, result.returncode)
        self.assertIn(f"baseline_raw_environment_invalid:{case_id}", payload.get("errors", []))

    def test_duplicate_manifest_key_is_rejected(self) -> None:
        raw = self.manifest_path.read_text(encoding="utf-8")
        self.manifest_path.write_text(
            raw.replace(
                '  "schema_version": "1.0",',
                '  "schema_version": "1.0",\n  "schema_version": "1.0",',
                1,
            ),
            encoding="utf-8",
        )
        result, payload = self.verify()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("baseline_manifest_invalid", payload.get("errors", []))


if __name__ == "__main__":
    unittest.main()
