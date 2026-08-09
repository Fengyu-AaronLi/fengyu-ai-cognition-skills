from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseLoopContractTests(unittest.TestCase):
    def test_workflow_has_unbounded_blocker_driven_loop(self) -> None:
        workflow = (ROOT / "workflows" / "v2-evolution.yaml").read_text(encoding="utf-8")
        for marker in (
            "loop_controller:",
            "candidate_runtime_sha256",
            "frozen_red_test_sha256",
            "blocker_count",
            "next_iteration",
            "invalidate_audit",
            "zero_blocker_exit",
            "no_fixed_iteration_limit",
            "independent_attribution_audit",
            "independent_clinical_safety_audit",
            "independent_state_integrity_audit",
            "release_package_audit",
        ):
            self.assertIn(marker, workflow)

    def test_makefile_exposes_every_known_regression_loop_and_release_gate(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        for marker in (
            "v7-loop:",
            "v8-loop:",
            "v9-loop:",
            "release-package:",
            "release-package-check:",
            "scripts/build_package.py build",
            "scripts/build_package.py verify",
            "test_release_package.py",
        ):
            self.assertIn(marker, makefile)

    def test_top_level_workflow_executes_the_manifest_bound_current_dag(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        workflow = (ROOT / "workflows" / "v51-final-release.json").read_text(
            encoding="utf-8"
        )
        self.assertIn("scripts/run_evolution.py run", makefile)
        self.assertIn("$(WORKFLOW_PATH)", makefile)
        self.assertIn("scripts/run_regressions.py", workflow)
        self.assertIn("--test-manifest", workflow)
        self.assertIn("evals/test-generation-manifest.json", workflow)

    def test_installed_skill_explains_source_checkout_and_package_verification(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        quickstart = (ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8")
        for text in (skill, quickstart):
            self.assertIn("scripts/build_package.py", text)
            self.assertIn("verify --package", text)
            self.assertIn("PACKAGE-MANIFEST.json", text)
        self.assertIn("完整源码仓库", skill)
        self.assertIn("最小安装包", skill)

    def test_safety_boundary_reference_is_explicit_and_source_bounded(self) -> None:
        safety = (ROOT / "references" / "safety-boundaries.md").read_text(encoding="utf-8")
        problem = (ROOT / "problem-spec.md").read_text(encoding="utf-8")
        provenance = (ROOT / "PROVENANCE.md").read_text(encoding="utf-8")
        for marker in (
            "who.int",
            "nimh.nih.gov",
            "healthdirect.gov.au",
            "poisonsinfo.nsw.gov.au",
            "不得催吐",
            "不得凭空补充危险手段或症状",
            "不能完成个案风险评估",
        ):
            self.assertIn(marker, safety)
        self.assertIn("毒物信息中心", problem)
        self.assertIn("NSW Poisons Information Centre", provenance)

    def test_repository_level_attribution_registers_this_component(self) -> None:
        repo_root = ROOT.parents[1]
        registry = (repo_root / "provenance.yml").read_text(encoding="utf-8")
        notice = (repo_root / "NOTICE.md").read_text(encoding="utf-8")
        for text in (registry, notice):
            self.assertIn("breaking-identity-labels", text)
            self.assertIn("8282f010964601070334dd7350973386abff6d2b", text)
            self.assertIn("CC BY-NC 4.0", text.replace("CC-BY-NC-4.0", "CC BY-NC 4.0"))
        self.assertIn("copied_examples: false", registry)
        self.assertIn("publication_ready: false", registry)


if __name__ == "__main__":
    unittest.main()
