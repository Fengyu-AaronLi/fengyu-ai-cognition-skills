#!/usr/bin/env python3
"""R68 red contracts for a closed, reproducible dependency inventory.

The test-generation manifest proves which test modules ran.  These tests define
the separate, immutable non-test input closure that those modules and the
release workflow are allowed to read.  The dependency manifest is generated
only by an explicit command and is never repaired by a regression run.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parents[1]
SYNC_TOOL = ROOT / "scripts" / "sync_regression_dependencies.py"
RUN_REGRESSIONS = ROOT / "scripts" / "run_regressions.py"
MANIFEST = ROOT / "evals" / "regression-dependency-manifest.json"

REPOSITORY_DEPENDENCIES = {"LICENSE", "NOTICE.md", "provenance.yml"}
CORE_TOP_LEVEL_FILES = {
    "LICENSE",
    "Makefile",
    "NOTICE.md",
    "PROVENANCE.md",
    "README.md",
    "SKILL.md",
    "SOURCE_OF_TRUTH.md",
    "VERSION",
    "problem-spec.md",
    "zero-threshold-prompt.md",
}
IMMUTABLE_TREES = (
    "agents",
    "docs",
    "examples",
    "launch",
    "references",
    "schemas",
    "scripts",
    "templates",
    "workflows",
)
FORBIDDEN_EXACT = {
    "evals/evolution-log.md",
    "evals/regression-dependency-manifest.json",
    "evals/release-gate.json",
}
FORBIDDEN_PREFIXES = (
    "evals/blocker-resolutions/",
    "evals/receipts/",
    "evals/runs/",
    "dist/",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def is_forbidden_skill_path(relative: str) -> bool:
    path = Path(relative)
    return (
        relative in FORBIDDEN_EXACT
        or any(relative.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)
        or "__pycache__" in path.parts
        or "dist" in path.parts
        or path.suffix == ".pyc"
        or path.name.endswith(".lock")
    )


def expected_inventory(skill_root: Path, repository_root: Path) -> set[tuple[str, str]]:
    """Independently derive the closed world the synchronizer must enumerate."""

    expected = {
        ("repository", relative) for relative in REPOSITORY_DEPENDENCIES
    }
    expected.update(("skill", relative) for relative in CORE_TOP_LEVEL_FILES)
    for directory in IMMUTABLE_TREES:
        tree = skill_root / directory
        if not tree.exists():
            continue
        for path in tree.rglob("*"):
            relative = path.relative_to(skill_root).as_posix()
            if path.is_symlink():
                continue
            if path.is_file() and not is_forbidden_skill_path(relative):
                expected.add(("skill", relative))

    evals_root = skill_root / "evals"
    if evals_root.is_dir():
        # Direct evaluation contracts are source inputs.  Large historical raw
        # run trees are outputs, so only the current baseline/live evidence,
        # red-ledger evidence and migration evidence enter this non-test closure.
        for path in evals_root.iterdir():
            relative = path.relative_to(skill_root).as_posix()
            if path.is_file() and not path.is_symlink() and not is_forbidden_skill_path(relative):
                expected.add(("skill", relative))
        schema_root = evals_root / "schemas"
        if schema_root.is_dir():
            expected.update(
                ("skill", path.relative_to(skill_root).as_posix())
                for path in schema_root.rglob("*")
                if path.is_file() and not path.is_symlink()
            )

        baseline_manifest = evals_root / "baseline-evidence-manifest.json"
        if baseline_manifest.is_file():
            baseline = load_manifest(baseline_manifest)
            baseline_paths = [
                item.get("path") for item in baseline.get("bindings", {}).values()
            ]
            baseline_paths.extend(
                case.get("raw_record", {}).get("path")
                for case in baseline.get("cases", [])
            )
            for relative in filter(None, baseline_paths):
                expected.add(("skill", relative))

        live_manifest_path = evals_root / "live-e2e-manifest.json"
        if live_manifest_path.is_file():
            live = load_manifest(live_manifest_path)
            for binding in live.get("bindings", {}).values():
                relative = binding.get("path")
                if relative:
                    expected.add(("skill", relative))
            live_paths = [
                Path(case["run"]["path"])
                for case in live.get("cases", [])
                if case.get("run", {}).get("path")
            ]
            review_path = live.get("review", {}).get("path")
            if review_path:
                live_paths.append(Path(review_path))
            if live_paths:
                live_root = skill_root / os.path.commonpath(
                    [str(path.parent) for path in live_paths]
                )
                expected.update(
                    ("skill", path.relative_to(skill_root).as_posix())
                    for path in live_root.rglob("*")
                    if path.is_file() and not path.is_symlink()
                )

        red_manifest_path = evals_root / "red-evidence-manifest.json"
        if red_manifest_path.is_file():
            red_manifest = load_manifest(red_manifest_path)
            for record in red_manifest.get("records", []):
                evidence = record.get("evidence", {})
                relative = evidence.get("path")
                if relative:
                    expected.add(("skill", relative))

        migrations_root = evals_root / "test-migrations"
        if migrations_root.is_dir():
            for receipt in migrations_root.glob("*.json"):
                expected.add(("skill", receipt.relative_to(skill_root).as_posix()))
                migration = load_manifest(receipt)
                for evidence in migration.get("evidence", []):
                    relative = evidence.get("path")
                    if relative:
                        expected.add(("skill", relative))

        preregistration = (
            evals_root
            / "raw/v2-forward/attribution-blind-v9/preregistration.json"
        )
        if preregistration.is_file():
            expected.add(
                ("skill", preregistration.relative_to(skill_root).as_posix())
            )

    missing_repo = [
        relative
        for relative in REPOSITORY_DEPENDENCIES
        if not (repository_root / relative).is_file()
    ]
    missing_core = [
        relative for relative in CORE_TOP_LEVEL_FILES if not (skill_root / relative).is_file()
    ]
    if missing_repo or missing_core:
        raise AssertionError(
            f"fixture/source is missing inventory anchors: repo={missing_repo}, "
            f"skill={missing_core}"
        )
    return expected


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_identities(path: Path) -> set[tuple[str, str]]:
    payload = load_manifest(path)
    return {(item["scope"], item["path"]) for item in payload["files"]}


def write_file(path: Path, content: str = "fixture\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class InventoryFixture:
    """A small repository with every inventory family and generated decoys."""

    def __init__(self, base: Path) -> None:
        self.repository_root = base / "repo"
        self.skill_root = (
            self.repository_root / "skills" / "breaking-identity-labels"
        )
        self.manifest = (
            self.skill_root / "evals" / "regression-dependency-manifest.json"
        )
        self._populate()

    def _populate(self) -> None:
        for relative in REPOSITORY_DEPENDENCIES:
            write_file(self.repository_root / relative, f"repository {relative}\n")
        write_file(
            self.repository_root / "README.md",
            "repository decoy must not become a dependency\n",
        )
        for relative in CORE_TOP_LEVEL_FILES:
            write_file(self.skill_root / relative, f"skill {relative}\n")

        immutable = {
            "agents/openai.yaml": "name: fixture\n",
            "docs/acceptance.md": "acceptance\n",
            "launch/video-brief.md": "brief skeleton\n",
            "references/policy-rules.md": "policy\n",
            "schemas/analysis.schema.json": "{}\n",
            "scripts/runtime.py": "VALUE = 1\n",
            "templates/analysis.json": "{}\n",
            "workflows/roles/reviewer.md": "reviewer\n",
            "workflows/current.json": "{}\n",
            "workflows/historical.json": "{}\n",
            "examples/demo.md": "demo\n",
            "examples/real-run/analysis.json": "{}\n",
            "examples/real-run/report.md": "report\n",
            "evals/cases.json": "[]\n",
            "evals/rubric.md": "rubric\n",
            "evals/baseline-report.md": "baseline\n",
            "evals/raw/baseline/C01.md": "raw baseline\n",
            "evals/raw/current-live-e2e/C01/run.json": "{}\n",
            "evals/raw/current-live-e2e/C01/model-analysis.raw.json": "{}\n",
            "evals/raw/current-live-e2e/review.json": "{}\n",
            "evals/raw/migration/red.md": "red evidence\n",
            "evals/run_v2_evals.py": "VALUE = 1\n",
            "evals/test-generation-manifest.json": "{}\n",
        }
        for relative, content in immutable.items():
            write_file(self.skill_root / relative, content)

        baseline = {
            "schema_version": "1.0",
            "bindings": {
                "cases": {"path": "evals/cases.json"},
                "rubric": {"path": "evals/rubric.md"},
                "report": {"path": "evals/baseline-report.md"},
            },
            "cases": [
                {"raw_record": {"path": "evals/raw/baseline/C01.md"}}
            ],
        }
        write_file(
            self.skill_root / "evals/baseline-evidence-manifest.json",
            canonical_json(baseline).decode("utf-8"),
        )
        live = {
            "schema_version": "1.0",
            "bindings": {
                "skill": {"path": "SKILL.md"},
                "runtime": {"path": "scripts/runtime.py"},
            },
            "cases": [
                {
                    "case_id": "C01",
                    "run": {
                        "path": "evals/raw/current-live-e2e/C01/run.json"
                    },
                }
            ],
            "review": {"path": "evals/raw/current-live-e2e/review.json"},
        }
        write_file(
            self.skill_root / "evals/live-e2e-manifest.json",
            canonical_json(live).decode("utf-8"),
        )
        migration_evidence = self.skill_root / "evals/raw/migration/red.md"
        migration = {
            "schema_version": "1.0",
            "receipt_id": "fixture-migration",
            "evidence": [
                {
                    "path": "evals/raw/migration/red.md",
                    "sha256": sha256_file(migration_evidence),
                }
            ],
        }
        write_file(
            self.skill_root / "evals/test-migrations/fixture.json",
            canonical_json(migration).decode("utf-8"),
        )

        generated = {
            "evals/evolution-log.md": "mutable\n",
            "evals/release-gate.json": "{}\n",
            "evals/runs/run-1/state.json": "{}\n",
            "evals/receipts/audit/receipt.json": "{}\n",
            "evals/blocker-resolutions/resolution.json": "{}\n",
            "examples/real-run/.case.lock": "lock\n",
            "scripts/__pycache__/runtime.cpython-314.pyc": "cache\n",
            "dist/package.zip": "archive\n",
        }
        for relative, content in generated.items():
            write_file(self.skill_root / relative, content)

        write_file(self.manifest, '{"stale":true}\n')


def run_sync(mode: str, fixture: InventoryFixture) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SYNC_TOOL),
            mode,
            "--manifest",
            str(fixture.manifest),
            "--skill-root",
            str(fixture.skill_root),
            "--repository-root",
            str(fixture.repository_root),
        ],
        cwd=fixture.skill_root,
        text=True,
        capture_output=True,
        check=False,
    )


def command_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


class CurrentDependencyInventoryTests(unittest.TestCase):
    def test_synchronizer_exists_and_current_manifest_passes_check(self) -> None:
        self.assertTrue(
            SYNC_TOOL.is_file(),
            "dependency closure needs an executable sync/check tool",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(SYNC_TOOL),
                "check",
                "--manifest",
                str(MANIFEST),
                "--skill-root",
                str(ROOT),
                "--repository-root",
                str(REPOSITORY_ROOT),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, command_output(result))

    def test_current_manifest_is_the_exact_non_test_inventory(self) -> None:
        expected = expected_inventory(ROOT, REPOSITORY_ROOT)
        observed = manifest_identities(MANIFEST)
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        if missing or extra:
            self.fail(
                "the dependency manifest must be a closed inventory, not a hand-picked "
                f"sample; missing={len(missing)} {missing[:12]!r}; "
                f"extra={len(extra)} {extra[:12]!r}"
            )

    def test_repository_scope_is_exactly_license_notice_and_provenance(self) -> None:
        observed = {
            path
            for scope, path in manifest_identities(MANIFEST)
            if scope == "repository"
        }
        self.assertEqual(REPOSITORY_DEPENDENCIES, observed)

    def test_source_workflows_roles_and_real_demo_are_covered(self) -> None:
        observed = manifest_identities(MANIFEST)
        required = {
            ("skill", path.relative_to(ROOT).as_posix())
            for pattern in (
                "scripts/*.py",
                "schemas/*.json",
                "docs/**/*",
                "references/**/*",
                "workflows/**/*",
                "examples/real-run/*",
            )
            for path in ROOT.glob(pattern)
            if path.is_file()
            and not path.is_symlink()
            and not is_forbidden_skill_path(path.relative_to(ROOT).as_posix())
        }
        required.update(("skill", path) for path in CORE_TOP_LEVEL_FILES)
        missing = sorted(required - observed)
        if missing:
            self.fail(
                f"source dependency families are missing ({len(missing)}): "
                + ", ".join(path for _, path in missing[:20])
            )

    def test_baseline_live_e2e_migrations_and_evidence_are_covered(self) -> None:
        observed = manifest_identities(MANIFEST)
        required = {
            ("skill", "evals/baseline-evidence-manifest.json"),
            ("skill", "evals/live-e2e-manifest.json"),
        }
        for directory in (ROOT / "evals/raw/baseline",):
            required.update(
                ("skill", path.relative_to(ROOT).as_posix())
                for path in directory.rglob("*")
                if path.is_file() and not path.is_symlink()
            )
        live_manifest = load_manifest(ROOT / "evals/live-e2e-manifest.json")
        live_run_paths = [Path(case["run"]["path"]) for case in live_manifest["cases"]]
        live_run_paths.append(Path(live_manifest["review"]["path"]))
        live_root = ROOT / os.path.commonpath(
            [str(path.parent) for path in live_run_paths]
        )
        required.update(
            ("skill", path.relative_to(ROOT).as_posix())
            for path in live_root.rglob("*")
            if path.is_file() and not path.is_symlink()
        )
        for receipt in (ROOT / "evals/test-migrations").glob("*.json"):
            required.add(("skill", receipt.relative_to(ROOT).as_posix()))
            payload = load_manifest(receipt)
            required.update(
                ("skill", evidence["path"])
                for evidence in payload.get("evidence", [])
            )
        missing = sorted(required - observed)
        if missing:
            self.fail(
                "baseline, current live E2E, migration receipts or their evidence "
                f"are missing ({len(missing)}): "
                + ", ".join(path for _, path in missing[:20])
            )


class DependencySynchronizerBehaviorTests(unittest.TestCase):
    def make_fixture(self, base: Path) -> InventoryFixture:
        return InventoryFixture(base)

    def assert_failed_with(
        self,
        result: subprocess.CompletedProcess[str],
        code: str,
    ) -> None:
        self.assertNotEqual(0, result.returncode, command_output(result))
        self.assertIn(code, command_output(result))

    def sync_fixture(self, base: Path) -> InventoryFixture:
        fixture = self.make_fixture(base)
        result = run_sync("sync", fixture)
        self.assertEqual(0, result.returncode, command_output(result))
        return fixture

    def test_sync_is_explicit_canonical_and_atomically_replaces_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v68-deps-") as temp:
            fixture = self.make_fixture(Path(temp))
            stale = fixture.manifest.read_bytes()
            stale_inode = fixture.manifest.stat().st_ino

            check = run_sync("check", fixture)
            self.assertNotEqual(0, check.returncode)
            self.assertEqual(stale, fixture.manifest.read_bytes(), "check must be read-only")

            sync = run_sync("sync", fixture)
            self.assertEqual(0, sync.returncode, command_output(sync))
            self.assertNotEqual(
                stale_inode,
                fixture.manifest.stat().st_ino,
                "sync must replace a fully written temporary file atomically",
            )
            payload = load_manifest(fixture.manifest)
            self.assertEqual(canonical_json(payload), fixture.manifest.read_bytes())
            identities = [
                (item["scope"], item["path"]) for item in payload["files"]
            ]
            self.assertEqual(sorted(set(identities)), identities)
            self.assertEqual(
                expected_inventory(fixture.skill_root, fixture.repository_root),
                set(identities),
            )

            before_check = fixture.manifest.read_bytes()
            good_check = run_sync("check", fixture)
            self.assertEqual(0, good_check.returncode, command_output(good_check))
            self.assertEqual(before_check, fixture.manifest.read_bytes())
            leftovers = [
                path.name
                for path in fixture.manifest.parent.iterdir()
                if path.name != fixture.manifest.name and ".tmp" in path.name
            ]
            self.assertEqual([], leftovers, "atomic sync must not leave temp files")

    def test_check_fails_closed_on_missing_extra_and_hash_drift(self) -> None:
        variants = ("missing", "extra", "hash")
        for variant in variants:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory(
                prefix=f"identity-v68-{variant}-"
            ) as temp:
                fixture = self.sync_fixture(Path(temp))
                payload = load_manifest(fixture.manifest)
                if variant == "missing":
                    payload["files"].pop(0)
                    fixture.manifest.write_bytes(canonical_json(payload))
                    expected_code = "dependency_inventory_missing"
                elif variant == "extra":
                    extra = fixture.skill_root / "misc/untracked.txt"
                    write_file(extra, "not an inventory dependency\n")
                    payload["files"].append(
                        {
                            "scope": "skill",
                            "path": "misc/untracked.txt",
                            "sha256": sha256_file(extra),
                        }
                    )
                    payload["files"].sort(key=lambda item: (item["scope"], item["path"]))
                    fixture.manifest.write_bytes(canonical_json(payload))
                    expected_code = "dependency_inventory_extra"
                else:
                    target = fixture.skill_root / "README.md"
                    target.write_text("drifted\n", encoding="utf-8")
                    expected_code = "regression_dependency_hash_mismatch"
                self.assert_failed_with(run_sync("check", fixture), expected_code)

    def test_check_fails_closed_on_symlink_and_unsafe_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v68-symlink-") as temp:
            fixture = self.sync_fixture(Path(temp))
            target = fixture.skill_root / "README.md"
            external = Path(temp) / "external.txt"
            external.write_text("outside\n", encoding="utf-8")
            target.unlink()
            target.symlink_to(external)
            self.assert_failed_with(
                run_sync("check", fixture),
                "regression_dependency_symlink",
            )

        with tempfile.TemporaryDirectory(prefix="identity-v68-unsafe-") as temp:
            fixture = self.sync_fixture(Path(temp))
            payload = load_manifest(fixture.manifest)
            payload["files"][0]["path"] = "../escape.txt"
            fixture.manifest.write_bytes(canonical_json(payload))
            self.assert_failed_with(
                run_sync("check", fixture),
                "regression_dependency_unsafe_path",
            )

    def test_generated_mutable_and_self_paths_are_excluded_and_rejected(self) -> None:
        forbidden = (
            "evals/regression-dependency-manifest.json",
            "evals/release-gate.json",
            "evals/runs/run-1/state.json",
            "evals/receipts/audit/receipt.json",
            "evals/blocker-resolutions/resolution.json",
            "evals/evolution-log.md",
            "examples/real-run/.case.lock",
            "scripts/__pycache__/runtime.cpython-314.pyc",
            "dist/package.zip",
        )
        with tempfile.TemporaryDirectory(prefix="identity-v68-forbidden-") as temp:
            fixture = self.sync_fixture(Path(temp))
            clean = load_manifest(fixture.manifest)
            identities = {
                (item["scope"], item["path"]) for item in clean["files"]
            }
            self.assertFalse(
                {("skill", path) for path in forbidden} & identities,
                "sync must not bind mutable outputs, itself, locks or caches",
            )

            for relative in forbidden:
                with self.subTest(relative=relative):
                    payload = json.loads(json.dumps(clean))
                    target = fixture.skill_root / relative
                    payload["files"].append(
                        {
                            "scope": "skill",
                            "path": relative,
                            "sha256": sha256_file(target),
                        }
                    )
                    payload["files"].sort(key=lambda item: (item["scope"], item["path"]))
                    fixture.manifest.write_bytes(canonical_json(payload))
                    self.assert_failed_with(
                        run_sync("check", fixture),
                        "regression_dependency_forbidden_path",
                    )

    def test_full_regression_never_repairs_dependency_manifest(self) -> None:
        payload = load_manifest(MANIFEST)
        payload["files"][0]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory(prefix="identity-v68-runner-") as temp:
            probe = Path(temp) / "dependency-manifest.json"
            probe.write_bytes(canonical_json(payload))
            before = probe.read_bytes()
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUN_REGRESSIONS),
                    "--suite",
                    "architecture",
                    "--test-manifest",
                    str(ROOT / "evals/test-generation-manifest.json"),
                    "--dependency-manifest",
                    str(probe),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(
                before,
                probe.read_bytes(),
                "full regression must fail; it must never invoke sync or rewrite evidence",
            )


if __name__ == "__main__":
    unittest.main()
