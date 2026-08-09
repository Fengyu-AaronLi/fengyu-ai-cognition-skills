#!/usr/bin/env python3
"""R66 red contracts for dependency closure and immutable installed use."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parents[1]
AUDIT_HARNESS = ROOT / "scripts" / "run_release_audits.py"
PACKAGE_BUILDER = ROOT / "scripts" / "build_package.py"
REGRESSION_DEPENDENCY_MANIFEST = ROOT / "evals" / "regression-dependency-manifest.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def current_workflow_path() -> Path:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(
        r"^WORKFLOW_PATH\s*(?:\?=|:=|=)\s*(\S+)\s*$",
        makefile,
        flags=re.MULTILINE,
    )
    if match is None:
        raise AssertionError("Makefile must declare one current WORKFLOW_PATH")
    return ROOT / match.group(1)


def file_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


class AuditInputClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.audit = load_module("v66_release_audits", AUDIT_HARNESS)

    def resolved_inputs_for_test(self, audit_id: str, test_path: str) -> set[Path]:
        commands = self.audit.AUDIT_SUITES[audit_id]
        matches = [
            (index, command)
            for index, command in enumerate(commands)
            if command[0] == test_path
        ]
        self.assertEqual(
            1,
            len(matches),
            f"{audit_id} must execute {test_path} exactly once",
        )
        index, command = matches[0]
        evidence_dir = ROOT / "evals" / "receipts" / ".v66-closure-probe"
        return {
            path.resolve()
            for path in self.audit.audit_input_paths(
                audit_id,
                index,
                command,
                evidence_dir,
                require_available=True,
            )
        }

    def test_attribution_audit_authenticates_the_frozen_preregistration_it_reads(
        self,
    ) -> None:
        observed = self.resolved_inputs_for_test(
            "independent_attribution_audit",
            "tests/test_v10_attribution_blind_regressions.py",
        )
        required = (
            ROOT
            / "evals"
            / "raw"
            / "v2-forward"
            / "attribution-blind-v9"
            / "preregistration.json"
        ).resolve()
        self.assertIn(
            required,
            observed,
            "the audit receipt would stay green if the V9 preregistration changed",
        )

    def test_release_audit_authenticates_every_file_read_by_release_loop_contract(
        self,
    ) -> None:
        observed = self.resolved_inputs_for_test(
            "release_package_audit",
            "tests/test_release_loop_contract.py",
        )
        required = {
            (ROOT / "workflows" / "v2-evolution.yaml").resolve(),
            (ROOT / "Makefile").resolve(),
            (ROOT / "workflows" / "v51-final-release.json").resolve(),
            (REPOSITORY_ROOT / "provenance.yml").resolve(),
            (REPOSITORY_ROOT / "NOTICE.md").resolve(),
        }
        self.assertFalse(
            required - observed,
            "release audit input snapshot omits files read by the executed test: "
            + ", ".join(str(path) for path in sorted(required - observed)),
        )


class RegressionDependencyClosureTests(unittest.TestCase):
    def load_verified_manifest(self) -> dict:
        self.assertTrue(
            REGRESSION_DEPENDENCY_MANIFEST.is_file(),
            "full regression needs a separate hash-bound dependency manifest; "
            "the test-generation manifest authenticates test files, not files tests read",
        )
        payload = json.loads(
            REGRESSION_DEPENDENCY_MANIFEST.read_text(encoding="utf-8")
        )
        self.assertEqual("1.0", payload.get("schema_version"))
        records = payload.get("files")
        self.assertIsInstance(records, list)
        self.assertTrue(records)

        identities: list[tuple[str, str]] = []
        for record in records:
            self.assertIsInstance(record, dict)
            self.assertEqual({"scope", "path", "sha256"}, set(record))
            scope = record["scope"]
            relative = record["path"]
            self.assertIn(scope, {"skill", "repository"})
            self.assertIsInstance(relative, str)
            self.assertFalse(Path(relative).is_absolute())
            self.assertNotIn("..", Path(relative).parts)
            base = ROOT if scope == "skill" else REPOSITORY_ROOT
            target = (base / relative).resolve()
            target.relative_to(base.resolve())
            self.assertTrue(target.is_file() and not target.is_symlink(), target)
            self.assertEqual(record["sha256"], sha256_file(target), target)
            identities.append((scope, relative))
        self.assertEqual(sorted(set(identities)), identities)
        return payload

    def test_dependency_manifest_hash_binds_known_non_test_inputs(self) -> None:
        payload = self.load_verified_manifest()
        observed = {(item["scope"], item["path"]) for item in payload["files"]}
        required = {
            (
                "skill",
                "evals/raw/v2-forward/attribution-blind-v9/preregistration.json",
            ),
            ("skill", "workflows/v2-evolution.yaml"),
            ("skill", "Makefile"),
            ("skill", "workflows/v51-final-release.json"),
            ("repository", "provenance.yml"),
            ("repository", "NOTICE.md"),
        }
        self.assertFalse(
            required - observed,
            "regression dependency closure is missing known file reads: "
            + ", ".join(f"{scope}:{path}" for scope, path in sorted(required - observed)),
        )

    def test_current_full_regression_explicitly_consumes_dependency_manifest(
        self,
    ) -> None:
        workflow_path = current_workflow_path()
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        steps = {step["id"]: step for step in workflow["steps"]}
        step = steps["full_regression"]
        manifest_relative = REGRESSION_DEPENDENCY_MANIFEST.relative_to(ROOT).as_posix()
        self.assertIn(
            manifest_relative,
            step.get("input_files", []),
            "the command receipt must bind the dependency-manifest bytes",
        )
        argv = step["argv"]
        self.assertIn(
            "--dependency-manifest",
            argv,
            "run_regressions must verify the dependency manifest before importing tests",
        )
        self.assertIn(
            "{root}/" + manifest_relative,
            argv,
            "the workflow must pass the exact hash-bound dependency manifest",
        )


class InstalledPackageWorkspaceTests(unittest.TestCase):
    def installed_docs(self, package: Path | None = None) -> dict[str, str]:
        base = ROOT if package is None else package
        return {
            relative: (base / relative).read_text(encoding="utf-8")
            for relative in (
                "SKILL.md",
                "README.md",
                "docs/quickstart.md",
                "docs/evolution.md",
                "docs/acceptance.md",
            )
        }

    @staticmethod
    def has_external_workspace_contract(documents: dict[str, str]) -> bool:
        operational = "\n".join(
            documents[name]
            for name in ("SKILL.md", "README.md", "docs/quickstart.md")
        )
        immutable = re.search(
            r"SKILL_DIR[^\n]{0,100}(?:只读|不可写|不得写入|immutable)",
            operational,
            flags=re.IGNORECASE,
        )
        explicit_workdir = re.search(
            r"WORK_DIR[^\n]{0,160}(?:独立|唯一|外部|Skill[^\n]{0,40}(?:之外|外))",
            operational,
            flags=re.IGNORECASE,
        )
        commands_use_workdir = (
            'cd "$WORK_DIR"' in operational
            or '--text-file "$WORK_DIR/' in operational
            or '--out "$WORK_DIR/' in operational
        )
        return bool(immutable and explicit_workdir and commands_use_workdir)

    def test_installed_quick_run_requires_one_external_unique_work_directory(
        self,
    ) -> None:
        documents = self.installed_docs()
        self.assertTrue(
            self.has_external_workspace_contract(documents),
            "installed instructions must declare SKILL_DIR immutable and put every "
            "run's user-input, scaffold, analysis, case and state under a unique "
            "external WORK_DIR",
        )
        quick_run = documents["README.md"].split("## Quick run", 1)[-1].split(
            "## Operations", 1
        )[0]
        self.assertNotIn(
            "从 Skill 根目录执行",
            quick_run,
            "following this sentence mutates the installed allowlisted package",
        )

    def test_following_documented_first_run_keeps_installed_tree_verifiable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v66-installed-") as temp:
            temp_root = Path(temp)
            package = temp_root / "installed" / "breaking-identity-labels"
            package.parent.mkdir()
            build = subprocess.run(
                [
                    sys.executable,
                    str(PACKAGE_BUILDER),
                    "build",
                    "--out",
                    str(package),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, build.returncode, build.stdout + build.stderr)
            before = file_snapshot(package)
            docs = self.installed_docs(package)

            external = temp_root / "work" / "case-r66-001"
            run_dir = (
                external
                if self.has_external_workspace_contract(docs)
                else package
            )
            run_dir.mkdir(parents=True, exist_ok=True)
            input_path = run_dir / "user-input.txt"
            output_path = run_dir / "scaffold.json"
            input_path.write_text(
                "我是典型 I 人，所以我不适合带团队。\n",
                encoding="utf-8",
            )
            scaffold = subprocess.run(
                [
                    sys.executable,
                    str(package / "scripts" / "identity_label_case.py"),
                    "scaffold",
                    "--text-file",
                    str(input_path),
                    "--out",
                    str(output_path),
                ],
                cwd=run_dir,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, scaffold.returncode, scaffold.stdout + scaffold.stderr)

            after = file_snapshot(package)
            self.assertEqual(
                before,
                after,
                "one documented first-run step polluted the installed package with: "
                + ", ".join(sorted(set(after) - set(before))),
            )
            verify = subprocess.run(
                [
                    sys.executable,
                    str(package / "scripts" / "build_package.py"),
                    "verify",
                    "--package",
                    str(package),
                ],
                cwd=run_dir,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, verify.returncode, verify.stdout + verify.stderr)
            self.assertTrue(json.loads(verify.stdout)["valid"])

    def test_packaged_docs_mark_source_governance_commands_unavailable(self) -> None:
        source_only_tokens = (
            "make verify",
            "make workflow",
            "scripts/run_evolution.py",
            "scripts/run_release_audits.py",
            "sync-tests",
            "migrate-test",
        )
        missing_banners: list[str] = []
        for name, text in self.installed_docs().items():
            if not any(token in text for token in source_only_tokens):
                continue
            full_source = re.search(r"(?:仅|只)(?:在|限)[^\n]{0,80}完整源码", text)
            unavailable = re.search(
                r"最小(?:安装)?包[^\n]{0,160}(?:不含|不可用|无法运行|不能运行|不能执行)",
                text,
            )
            if full_source is None or unavailable is None:
                missing_banners.append(name)
        self.assertEqual(
            [],
            missing_banners,
            "packaged docs show source-only commands without an explicit installed-package "
            "unavailable boundary: " + ", ".join(missing_banners),
        )


if __name__ == "__main__":
    unittest.main()
