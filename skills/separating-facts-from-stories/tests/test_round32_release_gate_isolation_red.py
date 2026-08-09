from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
PACKAGER_PATH = SKILL_DIR / "scripts" / "package_runtime.py"
sys.path.insert(0, str(SKILL_DIR / "tests"))

import test_round4_release_gate_red as round4_release  # noqa: E402


class Round32ReleaseGateIsolationRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.packager = round4_release.load_module(
            "round32_package_runtime", PACKAGER_PATH
        )

    def test_source_root_unittest_shadow_cannot_forge_a_passing_gate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round32-shadow-") as temp_dir:
            source = Path(temp_dir) / "source"
            tests = source / "tests"
            tests.mkdir(parents=True)
            (source / "unittest.py").write_text(
                "print('Ran 1 test in 0.000s')\nprint('OK')\n",
                encoding="utf-8",
            )
            (tests / "test_contract.py").write_text(
                "import unittest\n"
                "class Contract(unittest.TestCase):\n"
                "    def test_must_fail(self): self.fail('real test executed')\n",
                encoding="utf-8",
            )
            evidence = {"test_contract": "tests/test_contract.py"}
            with mock.patch.object(
                self.packager, "REQUIRED_TEST_FILES", {"test_contract.py"}
            ), mock.patch.object(
                self.packager, "RELEASE_EVIDENCE_FILES", evidence
            ):
                with self.assertRaisesRegex(
                    OSError, "UNIT_TEST_GATE_FAILED"
                ):
                    self.packager.run_unit_test_gate(source)

    def test_test_source_created_during_run_invalidates_the_gate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round32-late-source-") as temp_dir:
            source = Path(temp_dir) / "source"
            tests = source / "tests"
            tests.mkdir(parents=True)
            (tests / "test_a_creator.py").write_text(
                "import pathlib\n"
                "import unittest\n"
                "class Creator(unittest.TestCase):\n"
                "    def test_create(self):\n"
                "        pathlib.Path(__file__).with_name('late_helper.py').write_text('VALUE = 11\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            (tests / "test_b_consumer.py").write_text(
                "import pathlib\n"
                "import sys\n"
                "import unittest\n"
                "sys.path.insert(0, str(pathlib.Path(__file__).parent))\n"
                "class Consumer(unittest.TestCase):\n"
                "    def test_import(self):\n"
                "        import late_helper\n"
                "        self.assertEqual(11, late_helper.VALUE)\n",
                encoding="utf-8",
            )
            evidence = {
                "test_a": "tests/test_a_creator.py",
                "test_b": "tests/test_b_consumer.py",
            }
            with mock.patch.object(
                self.packager,
                "REQUIRED_TEST_FILES",
                {"test_a_creator.py", "test_b_consumer.py"},
            ), mock.patch.object(
                self.packager, "RELEASE_EVIDENCE_FILES", evidence
            ):
                with self.assertRaisesRegex(
                    OSError, "UNIT_TEST_GATE_FAILED.*changed during execution"
                ):
                    self.packager.run_unit_test_gate(source)
            self.assertTrue((tests / "late_helper.py").is_file())

    def test_nested_malformed_release_evidence_returns_structured_invalid(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round32-manifest-") as temp_dir:
            helper = round4_release.Round4ReleaseGateRedTests()
            helper.packager = self.packager
            helper.runner = round4_release.load_module(
                "round32_run_evals", SKILL_DIR / "scripts" / "run_evals.py"
            )
            installed = helper._make_installed_tree(Path(temp_dir))
            manifest_path = installed / "runtime-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["release_evidence"]["skill"]["path"] = []
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            try:
                result = self.packager.verify_install(installed)
            except Exception as exc:  # pragma: no cover - the RED condition
                self.fail(
                    "nested malformed evidence must be rejected as data, not crash: "
                    f"{type(exc).__name__}: {exc}"
                )
            self.assertFalse(result["valid"])
            self.assertIn(
                "RELEASE_EVIDENCE_INVALID",
                {item["code"] for item in result["errors"]},
            )


if __name__ == "__main__":
    unittest.main()
