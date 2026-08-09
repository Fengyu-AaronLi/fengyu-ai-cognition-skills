#!/usr/bin/env python3
"""Round 171 RED: review attestations retain and verify source identity."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "tests"))
import test_round168_fixed_host_review_runner_red as round168  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Round171ReviewSourceIdentityRedTests(unittest.TestCase):
    def test_attestation_binds_source_identity_as_host_context(self) -> None:
        runner = load_module(
            "round171_runner", SKILL_DIR / "scripts" / "host_review_runner.py"
        )
        with tempfile.TemporaryDirectory(prefix="sffs-round171-green-") as temp_dir:
            root = Path(temp_dir).resolve()
            round168.write_minimal_repo(root)
            codex = root / "fixture-codex"
            round168.write_fake_codex(codex)
            result = runner.run_pair(repo_root=root, codex_path=codex)
            report_path = Path(result["review_attestations"]["p0_zero"])
            report = json.loads(report_path.read_text(encoding="utf-8"))
            identity = root / report["source_identity"]["path"]
            receipt = root / report["host_execution_receipt"]["path"]
            receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
            identity_sha = hashlib.sha256(identity.read_bytes()).hexdigest()
            self.assertEqual(identity_sha, report["source_identity"]["sha256"])
            self.assertEqual(
                identity_sha,
                receipt_payload["bindings"]["context_sha256"],
            )

    def test_tampered_source_identity_invalidates_review_attestation(self) -> None:
        runner = load_module(
            "round171_runner_tamper", SKILL_DIR / "scripts" / "host_review_runner.py"
        )
        host = load_module(
            "round171_host", SKILL_DIR / "scripts" / "codex_exec_host.py"
        )
        with tempfile.TemporaryDirectory(prefix="sffs-round171-tamper-") as temp_dir:
            root = Path(temp_dir).resolve()
            round168.write_minimal_repo(root)
            codex = root / "fixture-codex"
            round168.write_fake_codex(codex)
            result = runner.run_pair(repo_root=root, codex_path=codex)
            report = json.loads(
                Path(result["review_attestations"]["p0_zero"]).read_text(
                    encoding="utf-8"
                )
            )
            identity = root / report["source_identity"]["path"]
            payload = json.loads(identity.read_text(encoding="utf-8"))
            payload["files"]["README.md"] = "0" * 64
            identity.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            receipt = root / report["host_execution_receipt"]["path"]
            with self.assertRaisesRegex(
                host.HostExecutionError,
                "SOURCE_IDENTITY|HOST_BINDING",
            ):
                host.derive_review_attestation(
                    receipt_path=receipt,
                    repo_root=root,
                    attestation_type="p0_zero",
                    source_sha256=result["source_sha256"],
                )


if __name__ == "__main__":
    unittest.main()
