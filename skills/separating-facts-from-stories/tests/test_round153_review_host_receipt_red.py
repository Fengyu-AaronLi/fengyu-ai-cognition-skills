#!/usr/bin/env python3
"""Round 153 RED: review independence needs host-observed executions."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PRODUCER_PATH = (
    ROOT
    / "skills"
    / "separating-facts-from-stories"
    / "scripts"
    / "produce_release_gate.py"
)
sys.path.insert(0, str(PRODUCER_PATH.parents[1] / "tests"))
from host_execution_fixture import prepare_review_source, write_host_review  # noqa: E402


def load_producer():
    spec = importlib.util.spec_from_file_location("round153_producer", PRODUCER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load producer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Round153ReviewHostReceiptRedTests(unittest.TestCase):
    def test_two_self_declared_reviews_are_not_independence_evidence(self) -> None:
        producer = load_producer()
        with tempfile.TemporaryDirectory(prefix="sffs-round153-red-") as temp_dir:
            root = Path(temp_dir)

            def report(kind: str, suffix: str) -> dict[str, object]:
                artifact = root / f"{suffix}.md"
                artifact.write_text(f"self-authored review {suffix}\n", encoding="utf-8")
                return {
                    "schema_version": producer.SCHEMA_VERSION,
                    "attestation_type": kind,
                    "source_sha256": "a" * 64,
                    "reviewer_id": f"claimed-reviewer-{suffix}",
                    "execution_id": f"claimed-execution-{suffix}",
                    "model_environment": {
                        "runner": f"claimed-runner-{suffix}",
                        "model": "claimed-model",
                        "isolation": "claimed fresh execution",
                    },
                    "review_scope": list(producer.REQUIRED_REVIEW_SCOPE),
                    "covered_severities": ["P0", "P1"],
                    "review_artifact": {
                        "path": artifact.name,
                        "sha256": sha256(artifact),
                    },
                    "trust_boundary": producer.REVIEW_TRUST_BOUNDARY,
                    "findings": [],
                }

            p0 = report("p0_zero", "p0")
            p1 = report("reproducible_p1_zero", "p1")
            with self.assertRaisesRegex(ValueError, "host|receipt|execution"):
                producer.validate_review_pair(
                    p0,
                    p1,
                    source_sha256="a" * 64,
                    repo_root=root,
                )

    def test_two_host_observed_reviews_bind_identity_and_raw_payload(self) -> None:
        producer = load_producer()
        with tempfile.TemporaryDirectory(prefix="sffs-round153-green-") as temp_dir:
            root = Path(temp_dir)
            source_sha = prepare_review_source(root)
            _, p0 = write_host_review(
                root, "p0_zero", source_sha, suffix="host-a"
            )
            _, p1 = write_host_review(
                root, "reproducible_p1_zero", source_sha, suffix="host-b"
            )
            self.assertEqual(
                (0, 0),
                producer.validate_review_pair(
                    p0, p1, source_sha256=source_sha, repo_root=root
                ),
            )
            self.assertTrue(p0["reviewer_id"].startswith("host-"))
            self.assertTrue(p0["execution_id"].startswith("thread-"))

    def test_tampered_output_or_reused_receipt_fails_closed(self) -> None:
        producer = load_producer()
        with tempfile.TemporaryDirectory(prefix="sffs-round153-tamper-") as temp_dir:
            root = Path(temp_dir)
            source_sha = prepare_review_source(root)
            _, p0 = write_host_review(
                root, "p0_zero", source_sha, suffix="host-a"
            )
            _, p1 = write_host_review(
                root, "reproducible_p1_zero", source_sha, suffix="host-b"
            )
            reused = dict(p1)
            reused["host_execution_receipt"] = p0["host_execution_receipt"]
            with self.assertRaisesRegex(ValueError, "host execution receipt"):
                producer.validate_review_pair(
                    p0, reused, source_sha256=source_sha, repo_root=root
                )
            artifact = root / p0["review_artifact"]["path"]
            artifact.write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "host execution receipt|sha256"):
                producer.validate_review_pair(
                    p0, p1, source_sha256=source_sha, repo_root=root
                )


if __name__ == "__main__":
    unittest.main()
