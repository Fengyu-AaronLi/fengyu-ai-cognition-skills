from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
PACKAGER_PATH = SKILL_DIR / "scripts" / "package_runtime.py"
FIXTURE_DIR = (
    SKILL_DIR
    / "evals"
    / "raw"
    / "with-skill-v30-failed-attempts"
    / "round129-versioned-update-red-v401"
    / "long-narrative-exact-anchor"
)
FIXTURE_PATH = FIXTURE_DIR / "artifacts" / "separation.json"
RECEIPT_PATH = FIXTURE_DIR / "receipts" / "validation.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Round145InstalledLegacyTrustRuntimeRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.packager = _load_module("round145_packager", PACKAGER_PATH)
        cls.legacy = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))

    def test_trust_corpus_is_a_minimal_runtime_asset(self) -> None:
        self.assertIn(
            "evals/legacy-migration-corpus.json",
            self.packager.RUNTIME_FILES,
        )

    def test_clean_runtime_copy_accepts_only_the_attested_legacy_pair(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round145-") as temp_dir:
            installed = Path(temp_dir) / "separating-facts-from-stories"
            for relative in self.packager.RUNTIME_FILES:
                source = SKILL_DIR / relative
                target = installed / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

            runtime = _load_module(
                "round145_installed_casefile",
                installed / "scripts" / "casefile.py",
            )
            self.assertEqual(
                [],
                runtime.validate_casefile(
                    self.legacy,
                    legacy_receipt=self.receipt,
                ),
            )
            current = runtime.start_update(
                self.legacy,
                "我看到门口多了一把钥匙。",
                legacy_receipt=self.receipt,
            )
            self.assertEqual(runtime.CURRENT_VERSION_PAIR, runtime._casefile_version_pair(current))
            self.assertEqual(
                [],
                runtime.validate_casefile(
                    current,
                    previous=self.legacy,
                    legacy_receipt=self.receipt,
                ),
            )


if __name__ == "__main__":
    unittest.main()
