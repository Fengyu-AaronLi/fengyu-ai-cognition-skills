#!/usr/bin/env python3
"""R74 red contracts for a first-install operator using the runtime package."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_package.py"
SOURCE_RUNTIME = ROOT / "scripts" / "identity_label_case.py"
VALID_ANALYSIS = ROOT / "tests" / "fixtures" / "analysis-c01.json"
USER_TEXT = "我是典型 I 人，所以我不适合带团队，也不可能做好公开表达。"


def run_command(
    executable: Path,
    *args: str,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(executable), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def json_stdout(result: subprocess.CompletedProcess[str]) -> dict:
    if not result.stdout.strip():
        raise AssertionError(
            f"expected JSON stdout; exit={result.returncode}; stderr={result.stderr.strip()}"
        )
    return json.loads(result.stdout)


def snapshot_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def rehash_package_manifest(package: Path) -> None:
    """Re-seal an intentionally altered package without using source-tree bytes."""

    manifest_path = package / "PACKAGE-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for record in manifest["files"]:
        payload = (package / record["path"]).read_bytes()
        record["bytes"] = len(payload)
        record["sha256"] = sha256_bytes(payload)
    normalized = [
        {
            "path": item["path"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in sorted(manifest["files"], key=lambda item: item["path"])
    ]
    manifest["tree_sha256"] = sha256_bytes(
        json.dumps(
            normalized,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class InstalledAnalysisWorkOrderTests(unittest.TestCase):
    def build_package(self, root: Path) -> Path:
        package = root / "installed" / "breaking-identity-labels"
        package.parent.mkdir(parents=True)
        built = run_command(BUILDER, "build", "--out", str(package), cwd=ROOT)
        self.assertEqual(0, built.returncode, built.stdout + built.stderr)
        return package

    def test_installed_runtime_materializes_a_source_bound_analysis_work_order(
        self,
    ) -> None:
        """The first run must not depend on hand-copying a generic JSON template."""

        with tempfile.TemporaryDirectory(prefix="identity-v74-work-order-") as temp:
            temp_root = Path(temp)
            package = self.build_package(temp_root)
            runtime = package / "scripts" / "identity_label_case.py"
            work = temp_root / "work"
            work.mkdir()
            user_input = work / "user-input.txt"
            scaffold_path = work / "scaffold.json"
            analysis_path = work / "analysis.json"
            user_input.write_text(USER_TEXT, encoding="utf-8")

            scaffolded = run_command(
                runtime,
                "scaffold",
                "--text-file",
                str(user_input),
                "--out",
                str(scaffold_path),
                "--clock",
                "2026-08-07T00:00:00Z",
                cwd=work,
            )
            self.assertEqual(
                0, scaffolded.returncode, scaffolded.stdout + scaffolded.stderr
            )

            prepared = run_command(
                runtime,
                "prepare-analysis",
                "--scaffold",
                str(scaffold_path),
                "--out",
                str(analysis_path),
                cwd=work,
            )
            self.assertEqual(
                0,
                prepared.returncode,
                "the installed runtime has no executable analysis-work-order handoff:\n"
                + prepared.stdout
                + prepared.stderr,
            )
            response = json_stdout(prepared)
            self.assertTrue(response["valid"])
            self.assertEqual(str(analysis_path.resolve()), response["output"])
            analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
            scaffold = json.loads(scaffold_path.read_text(encoding="utf-8"))
            self.assertEqual(scaffold["analysis"], analysis)
            self.assertEqual("I 人", analysis["labels"][0]["text"])
            source = analysis["labels"][0]["source"]
            evidence = scaffold["evidence"][0]["text"]
            self.assertEqual(source["quote"], evidence[source["start"] : source["end"]])

    def test_missing_analysis_file_returns_a_stable_actionable_error(self) -> None:
        """A normal first-run omission must not surface a raw OS exception as its code."""

        with tempfile.TemporaryDirectory(prefix="identity-v74-analysis-error-") as temp:
            root = Path(temp)
            user_input = root / "user-input.txt"
            scaffold = root / "scaffold.json"
            user_input.write_text(USER_TEXT, encoding="utf-8")
            scaffolded = run_command(
                SOURCE_RUNTIME,
                "scaffold",
                "--text-file",
                str(user_input),
                "--out",
                str(scaffold),
                "--clock",
                "2026-08-07T00:00:00Z",
                cwd=root,
            )
            self.assertEqual(0, scaffolded.returncode, scaffolded.stdout + scaffolded.stderr)

            compiled = run_command(
                SOURCE_RUNTIME,
                "compile",
                "--scaffold",
                str(scaffold),
                "--analysis",
                str(root / "analysis.json"),
                "--out",
                str(root / "case.json"),
                "--clock",
                "2026-08-07T00:01:00Z",
                cwd=root,
            )
            self.assertNotEqual(0, compiled.returncode)
            error = json_stdout(compiled)["errors"][0]
            self.assertEqual(
                "analysis_file_missing",
                error["code"],
                "raw errno text is not a stable operator-facing error code",
            )
            self.assertRegex(
                error["message"],
                r"prepare-analysis|analysis\.json",
                "the failure must identify the concrete recovery action",
            )


class ExperimentConfirmationBoundaryTests(unittest.TestCase):
    def planned_case(self, root: Path) -> Path:
        case_dir = root / "case"
        initialized = run_command(
            SOURCE_RUNTIME,
            "init",
            "--text",
            USER_TEXT,
            "--case-dir",
            str(case_dir),
            "--clock",
            "2026-08-07T01:00:00Z",
            cwd=root,
        )
        self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
        planned = run_command(
            SOURCE_RUNTIME,
            "plan",
            "--case-dir",
            str(case_dir),
            "--analysis",
            str(VALID_ANALYSIS),
            "--expected-revision",
            "0",
            "--clock",
            "2026-08-07T01:01:00Z",
            cwd=root,
        )
        self.assertEqual(0, planned.returncode, planned.stdout + planned.stderr)
        return case_dir

    def test_start_without_user_confirmation_is_a_zero_write_failure(self) -> None:
        """`next` says confirmation is required, so `start` must enforce that gate."""

        with tempfile.TemporaryDirectory(prefix="identity-v74-no-confirm-") as temp:
            root = Path(temp)
            case_dir = self.planned_case(root)
            before = snapshot_files(case_dir)
            started = run_command(
                SOURCE_RUNTIME,
                "start",
                "--case-dir",
                str(case_dir),
                "--expected-revision",
                "1",
                "--clock",
                "2026-08-07T01:02:00Z",
                cwd=root,
            )
            self.assertNotEqual(
                0,
                started.returncode,
                "start advanced the experiment even though no user-confirmation artifact was supplied",
            )
            self.assertIn(
                "user_confirmation_required",
                {item["code"] for item in json_stdout(started)["errors"]},
            )
            self.assertEqual(before, snapshot_files(case_dir))

    def test_confirmed_start_binds_the_exact_user_words_into_the_event_chain(self) -> None:
        """Confirmation must be evidence, not an unaudited boolean asserted by the agent."""

        with tempfile.TemporaryDirectory(prefix="identity-v74-confirmed-") as temp:
            root = Path(temp)
            case_dir = self.planned_case(root)
            confirmation = root / "user-confirmation.txt"
            confirmation_text = "我愿意开始这个七天的小实验。"
            confirmation.write_text(confirmation_text, encoding="utf-8")
            started = run_command(
                SOURCE_RUNTIME,
                "start",
                "--case-dir",
                str(case_dir),
                "--confirmation-file",
                str(confirmation),
                "--expected-revision",
                "1",
                "--clock",
                "2026-08-07T01:02:00Z",
                cwd=root,
            )
            self.assertEqual(
                0,
                started.returncode,
                "the runtime has no file-backed confirmation path:\n"
                + started.stdout
                + started.stderr,
            )
            events = [
                json.loads(line)
                for line in (case_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            start_event = events[-1]
            self.assertEqual("start", start_event["type"])
            binding = start_event.get("user_confirmation")
            self.assertIsInstance(binding, dict)
            self.assertEqual(confirmation_text, binding["text"])
            self.assertEqual(
                sha256_bytes(confirmation_text.encode("utf-8")), binding["sha256"]
            )
            replayed = run_command(
                SOURCE_RUNTIME, "replay", "--case-dir", str(case_dir), cwd=root
            )
            self.assertEqual(0, replayed.returncode, replayed.stdout + replayed.stderr)


class InstalledPackageOperationalContractTests(unittest.TestCase):
    def build_package(self, root: Path) -> Path:
        package = root / "breaking-identity-labels"
        built = run_command(BUILDER, "build", "--out", str(package), cwd=ROOT)
        self.assertEqual(0, built.returncode, built.stdout + built.stderr)
        return package

    def test_package_verify_rejects_a_hash_valid_runtime_with_broken_compile(
        self,
    ) -> None:
        """`valid: true` must cover the promised handoff, not only help and scaffold."""

        with tempfile.TemporaryDirectory(prefix="identity-v74-package-smoke-") as temp:
            root = Path(temp)
            package = self.build_package(root)
            runtime = package / "scripts" / "identity_label_case.py"
            source = runtime.read_text(encoding="utf-8")
            needle = "def main() -> None:\n    args = parser().parse_args()\n"
            self.assertIn(needle, source)
            runtime.write_text(
                source.replace(
                    needle,
                    needle
                    + '    if args.command == "compile":\n'
                    + '        print("injected compile failure", file=sys.stderr)\n'
                    + "        raise SystemExit(77)\n",
                    1,
                ),
                encoding="utf-8",
            )
            rehash_package_manifest(package)

            verified = run_command(
                package / "scripts" / "build_package.py",
                "verify",
                "--package",
                str(package),
                cwd=root,
            )
            self.assertNotEqual(
                0,
                verified.returncode,
                "package verification returned valid after compile was deliberately broken; "
                "its smoke only proves help/scaffold",
            )
            self.assertIn("compile", (verified.stdout + verified.stderr).lower())

    def test_installed_layout_claims_are_distinguished_from_source_only_layout(
        self,
    ) -> None:
        """An installed README must not present excluded source roots as installed files."""

        with tempfile.TemporaryDirectory(prefix="identity-v74-package-docs-") as temp:
            package = self.build_package(Path(temp))
            readme = (package / "README.md").read_text(encoding="utf-8")
            block_match = re.search(r"```text\n(?P<body>breaking-identity-labels/.*?\n)```", readme, re.DOTALL)
            self.assertIsNotNone(block_match, "README is missing its architecture layout")
            assert block_match is not None
            layout = block_match.group("body")
            missing_claims = [
                token
                for token in (
                    "scripts/build_demo.py",
                    "tests/",
                    "evals/",
                    "examples/real-run/",
                )
                if token in layout and not (package / token.rstrip("/")).exists()
            ]
            prefix = readme[max(0, block_match.start() - 240) : block_match.start()]
            explicitly_source_only = re.search(
                r"完整源码(?:仓库|树|布局)|source(?: checkout| tree| layout)",
                prefix,
                flags=re.IGNORECASE,
            )
            self.assertTrue(
                not missing_claims or explicitly_source_only,
                "installed README presents absent allowlist-excluded paths without a "
                "source-only label: " + ", ".join(missing_claims),
            )


if __name__ == "__main__":
    unittest.main()
