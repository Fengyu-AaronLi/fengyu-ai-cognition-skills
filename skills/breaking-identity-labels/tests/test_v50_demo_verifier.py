from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_demo.py"
VERIFIER = ROOT / "scripts" / "verify_demo.py"


class DemoVerifierTests(unittest.TestCase):
    def run_verify(self, demo_dir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VERIFIER), "--demo-dir", str(demo_dir)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def build_demo(self, demo_dir: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(BUILDER),
                "--output-dir",
                str(demo_dir),
                "--clock",
                "2026-08-06T10:00:00Z",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_fresh_demo_passes_current_runtime_and_replay_checks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v50-demo-") as temporary:
            demo_dir = Path(temporary) / "demo"
            self.build_demo(demo_dir)
            result = self.run_verify(demo_dir)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["valid"])
            self.assertEqual(payload["replay"]["event_count"], 5)

    def test_artifact_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v50-demo-") as temporary:
            demo_dir = Path(temporary) / "demo"
            self.build_demo(demo_dir)
            with (demo_dir / "report.md").open("a", encoding="utf-8") as handle:
                handle.write("\ntampered\n")
            result = self.run_verify(demo_dir)
            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertIn("demo_artifact_hash_mismatch:report.md", payload["errors"])

    def test_stale_runtime_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v50-demo-") as temporary:
            demo_dir = Path(temporary) / "demo"
            self.build_demo(demo_dir)
            manifest_path = demo_dir / "run-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["runtime_sha256"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            result = self.run_verify(demo_dir)
            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertIn("demo_runtime_hash_mismatch", payload["errors"])


if __name__ == "__main__":
    unittest.main()
