#!/usr/bin/env python3
"""R75 red contracts for the installed package's persistent workflow smoke."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_package.py"
PACKAGE_NAME = "breaking-identity-labels"


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


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def snapshot_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def rehash_package_manifest(package: Path) -> None:
    """Re-seal a deliberately altered package using only its packaged bytes."""

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


def inject_after_parse(runtime: Path, injected_source: str) -> None:
    source = runtime.read_text(encoding="utf-8")
    needle = "def main() -> None:\n    args = parser().parse_args()\n"
    if needle not in source:
        raise AssertionError("runtime main parse boundary changed")
    runtime.write_text(
        source.replace(needle, needle + injected_source, 1),
        encoding="utf-8",
    )


class InstalledPersistentLifecycleSmokeTests(unittest.TestCase):
    def build_package(self, root: Path, name: str = "package") -> Path:
        package = root / name / PACKAGE_NAME
        package.parent.mkdir(parents=True)
        built = run_command(BUILDER, "build", "--out", str(package), cwd=ROOT)
        self.assertEqual(0, built.returncode, built.stdout + built.stderr)
        return package

    def verify_mutated_package(self, package: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
        rehash_package_manifest(package)
        return run_command(
            package / "scripts" / "build_package.py",
            "verify",
            "--package",
            str(package),
            cwd=cwd,
        )

    def test_runtime_smoke_declares_the_complete_persistent_loop_and_terminal_checks(
        self,
    ) -> None:
        """The package verifier must promise the actual state machine, not a prompt-like demo."""

        source = BUILDER.read_text(encoding="utf-8")
        start = source.index("def verify_runtime_smoke(")
        end = source.index("\ndef verify_privacy_boundary", start)
        smoke = source[start:end]

        missing_commands = [
            command
            for command in ("init", "plan", "start", "record", "review", "replay", "next")
            if f'"{command}"' not in smoke
        ]
        self.assertEqual(
            [],
            missing_commands,
            "runtime smoke does not execute the persistent lifecycle commands: "
            + ", ".join(missing_commands),
        )
        for required in (
            "--confirmation-file",
            "reviewed",
            "revision",
            "event_count",
            "latest_revision",
            "complete",
        ):
            self.assertIn(
                required,
                smoke,
                f"runtime smoke does not assert the terminal invariant {required!r}",
            )

    def test_verify_rejects_a_resealed_package_with_broken_review(self) -> None:
        """A package whose persistent review cannot run must not verify as usable."""

        with tempfile.TemporaryDirectory(prefix="identity-v75-review-") as temp:
            root = Path(temp)
            package = self.build_package(root)
            runtime = package / "scripts" / "identity_label_case.py"
            inject_after_parse(
                runtime,
                '    if args.command == "review":\n'
                '        print("injected persistent review failure", file=sys.stderr)\n'
                "        raise SystemExit(79)\n",
            )

            verified = self.verify_mutated_package(package, root)
            self.assertNotEqual(
                0,
                verified.returncode,
                "package verify accepted a hash-valid package whose review command is broken; "
                "the smoke did not reach the persistent lifecycle",
            )
            self.assertIn("review", (verified.stdout + verified.stderr).lower())

    def test_verify_rejects_replay_with_wrong_event_count(self) -> None:
        """Calling replay is insufficient unless the five-event, revision-four head is checked."""

        with tempfile.TemporaryDirectory(prefix="identity-v75-replay-") as temp:
            root = Path(temp)
            package = self.build_package(root)
            runtime = package / "scripts" / "identity_label_case.py"
            inject_after_parse(
                runtime,
                '    if args.command == "replay":\n'
                '        print(json.dumps({"valid": True, "event_count": 4, '
                '"latest_revision": 4, "errors": []}))\n'
                "        raise SystemExit(0)\n",
            )

            verified = self.verify_mutated_package(package, root)
            self.assertNotEqual(
                0,
                verified.returncode,
                "package verify accepted a replay that reported four events instead of five",
            )
            self.assertRegex(
                (verified.stdout + verified.stderr).lower(),
                r"replay|event.?count|five|5",
            )

    def test_verify_rejects_next_that_does_not_converge(self) -> None:
        """The installed loop is complete only when `next` reports the terminal state."""

        with tempfile.TemporaryDirectory(prefix="identity-v75-next-") as temp:
            root = Path(temp)
            package = self.build_package(root)
            runtime = package / "scripts" / "identity_label_case.py"
            inject_after_parse(
                runtime,
                '    if args.command == "next":\n'
                '        print(json.dumps({"workflow_version": "1.0", "case_id": "smoke", '
                '"revision": 4, "status": "reviewed", "route_mode": "deconstruct", '
                '"complete": False, "stage": "observation", "next_steps": [], "errors": []}))\n'
                "        raise SystemExit(0)\n",
            )

            verified = self.verify_mutated_package(package, root)
            self.assertNotEqual(
                0,
                verified.returncode,
                "package verify accepted a persistent loop whose next step never completed",
            )
            self.assertRegex(
                (verified.stdout + verified.stderr).lower(),
                r"next|complete|terminal",
            )

    def test_verify_keeps_package_and_installed_tree_free_of_case_state(self) -> None:
        """Persistent smoke state belongs in an external work directory only."""

        with tempfile.TemporaryDirectory(prefix="identity-v75-immutable-") as temp:
            root = Path(temp)
            package = self.build_package(root, "built")
            skills_dir = root / "installed-skills"
            installed_result = run_command(
                BUILDER,
                "install",
                "--package",
                str(package),
                "--skills-dir",
                str(skills_dir),
                cwd=ROOT,
            )
            self.assertEqual(
                0,
                installed_result.returncode,
                installed_result.stdout + installed_result.stderr,
            )
            installed = skills_dir / PACKAGE_NAME
            package_before = snapshot_files(package)
            installed_before = snapshot_files(installed)

            for candidate in (package, installed):
                verified = run_command(
                    candidate / "scripts" / "build_package.py",
                    "verify",
                    "--package",
                    str(candidate),
                    cwd=root,
                )
                self.assertEqual(0, verified.returncode, verified.stdout + verified.stderr)

            self.assertEqual(package_before, snapshot_files(package))
            self.assertEqual(installed_before, snapshot_files(installed))
            forbidden = {
                "case.json",
                "events.jsonl",
                "events.head.json",
                ".case.lock",
                ".case.transaction.json",
            }
            for candidate in (package, installed):
                leaked = sorted(
                    path.relative_to(candidate).as_posix()
                    for path in candidate.rglob("*")
                    if path.is_file() and path.name in forbidden
                )
                self.assertEqual(
                    [],
                    leaked,
                    f"package verification wrote persistent case state inside {candidate}",
                )


if __name__ == "__main__":
    unittest.main()
