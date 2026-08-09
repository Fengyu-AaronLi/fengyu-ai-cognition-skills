import fcntl
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
PACKAGER = SKILL_DIR / "scripts" / "package_runtime.py"
CASEFILE = SKILL_DIR / "scripts" / "casefile.py"
WORKFLOW = SKILL_DIR / "scripts" / "workflow.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Round13PackagedContractRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packager = load_module("round13_packager", PACKAGER)
        cls.casefile = load_module("round13_casefile", CASEFILE)

    def test_installed_markdown_has_no_broken_local_links(self):
        self.assertEqual(
            [],
            self.packager.validate_runtime_markdown_links(SKILL_DIR),
        )

    def test_packaged_markdown_gate_also_rejects_broken_local_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "separating-facts-from-stories"
            shutil.copytree(SKILL_DIR, source)
            readme = source / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8")
                + "\n![missing local diagram](assets/missing.png)\n",
                encoding="utf-8",
            )
            errors = self.packager.validate_runtime_markdown_links(source)
            self.assertTrue(
                any(item.get("target") == "assets/missing.png" for item in errors),
                errors,
            )

    def test_problem_and_upstream_audits_are_bound_into_runtime(self):
        for relative in ("problem-spec.md", "upstream-audit.md"):
            with self.subTest(relative=relative):
                self.assertIn(relative, self.packager.RUNTIME_FILES)
                self.assertIn(relative, self.packager.RELEASE_EVIDENCE_FILES.values())

    def test_packaged_self_test_covers_round11_safety_scope_regressions(self):
        result = self.casefile.runtime_self_test()
        required = {
            "safety_anchor_coverage_cross_span",
            "safety_reality_override",
            "safety_english_negation",
            "safety_resolved_history",
            "safety_meta_quote_scoped",
        }
        self.assertTrue(result["valid"], result)
        self.assertTrue(required.issubset(result["checks"]), result["checks"])
        self.assertTrue(all(result["checks"][name] for name in required))

    def test_safety_template_takes_the_shared_workspace_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input.txt"
            workspace = root / "session"
            source.write_text("他威胁今晚要杀我。", encoding="utf-8")
            started = subprocess.run(
                [
                    sys.executable,
                    str(WORKFLOW),
                    "start",
                    "--input",
                    str(source),
                    "--workspace",
                    str(workspace),
                    "--case-id",
                    "round13-lock",
                    "--mode",
                    "auto",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, started.returncode, started.stderr)
            lock_path = workspace / ".workflow.lock"
            with lock_path.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(WORKFLOW),
                        "safety-template",
                        "--workspace",
                        str(workspace),
                    ],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                time.sleep(0.15)
                self.assertIsNone(
                    process.poll(), "read-only template bypassed workspace lock"
                )
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                stdout, stderr = process.communicate(timeout=3)
            self.assertEqual(0, process.returncode, stderr)
            self.assertIn("当地警方", stdout)


if __name__ == "__main__":
    unittest.main()
