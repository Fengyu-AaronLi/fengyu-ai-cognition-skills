from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_package.py"


class ReleasePackageTests(unittest.TestCase):
    def run_builder(self, *args: str, expect: int = 0) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(BUILDER), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            expect,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result

    def test_build_is_allowlisted_hashed_and_runtime_smokable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "breaking-identity-labels"
            result = self.run_builder("build", "--out", str(package))
            summary = json.loads(result.stdout)
            self.assertEqual(summary["status"], "built")

            manifest_path = package / "PACKAGE-MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertRegex(manifest["tree_sha256"], r"^[0-9a-f]{64}$")
            declared = {item["path"] for item in manifest["files"]}
            actual = {
                path.relative_to(package).as_posix()
                for path in package.rglob("*")
                if path.is_file() and path.name != "PACKAGE-MANIFEST.json"
            }
            self.assertEqual(actual, declared)

            banned_roots = {"tests", "evals", "launch", "workflows", "examples"}
            self.assertFalse({path.split("/", 1)[0] for path in actual} & banned_roots)
            self.assertNotIn("scripts/build_demo.py", actual)
            self.assertIn("scripts/identity_label_case.py", actual)
            self.assertIn("LICENSE", actual)
            self.assertIn("references/safety-boundaries.md", actual)

            for item in manifest["files"]:
                payload = (package / item["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), item["sha256"])
                self.assertEqual(len(payload), item["bytes"])

            verify = self.run_builder("verify", "--package", str(package))
            verified = json.loads(verify.stdout)
            self.assertTrue(verified["valid"])
            self.assertEqual(verified["tree_sha256"], manifest["tree_sha256"])
            smoke = subprocess.run(
                [sys.executable, str(package / "scripts" / "identity_label_case.py"), "--help"],
                cwd=package,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(smoke.returncode, 0, msg=smoke.stderr)

    def test_zip_contains_only_the_verified_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "breaking-identity-labels"
            archive = Path(temp) / "breaking-identity-labels.zip"
            self.run_builder(
                "build",
                "--out",
                str(package),
                "--archive",
                str(archive),
            )
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
            self.assertIn("breaking-identity-labels/PACKAGE-MANIFEST.json", names)
            self.assertFalse(any("/evals/" in name or "/tests/" in name for name in names))
            verify = self.run_builder("verify", "--package", str(archive))
            self.assertTrue(json.loads(verify.stdout)["valid"])

    def test_install_refuses_to_overwrite_an_existing_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            package = base / "package" / "breaking-identity-labels"
            skills_dir = base / "skills"
            self.run_builder("build", "--out", str(package))
            first = self.run_builder(
                "install",
                "--package",
                str(package),
                "--skills-dir",
                str(skills_dir),
            )
            installed = Path(json.loads(first.stdout)["installed_at"])
            self.assertEqual(installed, (skills_dir / "breaking-identity-labels").resolve())
            self.assertTrue((installed / "PACKAGE-MANIFEST.json").is_file())

            sentinel = installed / "user-note.txt"
            sentinel.write_text("preserve", encoding="utf-8")
            second = self.run_builder(
                "install",
                "--package",
                str(package),
                "--skills-dir",
                str(skills_dir),
                expect=2,
            )
            self.assertIn("already exists", second.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_verify_rejects_hash_tampering_and_extra_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "breaking-identity-labels"
            self.run_builder("build", "--out", str(package))
            skill = package / "SKILL.md"
            original = skill.read_text(encoding="utf-8")
            skill.write_text(original + "\ntampered\n", encoding="utf-8")
            tampered = self.run_builder(
                "verify", "--package", str(package), expect=2
            )
            self.assertIn("mismatch", tampered.stderr)

            skill.write_text(original, encoding="utf-8")
            (package / "undeclared.txt").write_text("extra", encoding="utf-8")
            extra = self.run_builder("verify", "--package", str(package), expect=2)
            self.assertIn("boundary mismatch", extra.stderr)

    def test_build_is_byte_reproducible_and_refuses_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            package_a = base / "a"
            package_b = base / "b"
            archive_a = base / "a.zip"
            archive_b = base / "b.zip"
            self.run_builder(
                "build", "--out", str(package_a), "--archive", str(archive_a)
            )
            self.run_builder(
                "build", "--out", str(package_b), "--archive", str(archive_b)
            )
            self.assertEqual(archive_a.read_bytes(), archive_b.read_bytes())
            manifest_a = (package_a / "PACKAGE-MANIFEST.json").read_bytes()
            manifest_b = (package_b / "PACKAGE-MANIFEST.json").read_bytes()
            self.assertEqual(manifest_a, manifest_b)

            sentinel = package_a / "user-note.txt"
            sentinel.write_text("preserve", encoding="utf-8")
            refused = self.run_builder("build", "--out", str(package_a), expect=2)
            self.assertIn("already exists", refused.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_verify_rejects_archive_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "malicious.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("breaking-identity-labels/../../escaped.txt", "no")
            result = self.run_builder("verify", "--package", str(archive), expect=2)
            self.assertIn("unsafe path", result.stderr)

    def test_verify_rejects_archive_members_outside_the_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "extra.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("breaking-identity-labels/undeclared.txt", "extra")
            result = self.run_builder("verify", "--package", str(archive), expect=2)
            self.assertIn("archive member boundary", result.stderr)

    def test_verify_rejects_oversized_archive_members_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "oversized.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr(
                    "breaking-identity-labels/SKILL.md",
                    b"x" * 5_000_001,
                )
            result = self.run_builder("verify", "--package", str(archive), expect=2)
            self.assertIn("archive size limit", result.stderr)

    def test_verify_rejects_private_paths_even_after_manifest_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "breaking-identity-labels"
            self.run_builder("build", "--out", str(package))
            readme = package / "README.md"
            payload = readme.read_bytes() + b"\n/Users/example/private-case.json\n"
            readme.write_bytes(payload)

            manifest_path = package / "PACKAGE-MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            record = next(item for item in manifest["files"] if item["path"] == "README.md")
            record["bytes"] = len(payload)
            record["sha256"] = hashlib.sha256(payload).hexdigest()
            normalized = [
                {
                    "path": item["path"],
                    "bytes": item["bytes"],
                    "sha256": item["sha256"],
                }
                for item in sorted(manifest["files"], key=lambda item: item["path"])
            ]
            manifest["tree_sha256"] = hashlib.sha256(
                json.dumps(
                    normalized,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            result = self.run_builder("verify", "--package", str(package), expect=2)
            self.assertIn("privacy", result.stderr.lower())

    def test_verify_rejects_a_forged_tree_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "breaking-identity-labels"
            self.run_builder("build", "--out", str(package))
            manifest_path = package / "PACKAGE-MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["tree_sha256"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = self.run_builder("verify", "--package", str(package), expect=2)
            self.assertIn("tree digest", result.stderr)


if __name__ == "__main__":
    unittest.main()
