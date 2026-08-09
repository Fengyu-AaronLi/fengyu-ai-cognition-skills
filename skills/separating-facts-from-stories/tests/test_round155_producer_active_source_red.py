#!/usr/bin/env python3
"""Round 155 RED: release proof follows the active post-fix source epoch."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
PRODUCER_PATH = SKILL_DIR / "scripts" / "produce_release_gate.py"


def load_producer():
    spec = importlib.util.spec_from_file_location("round155_producer", PRODUCER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load producer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReachedRetention(RuntimeError):
    pass


class Round155ProducerActiveSourceRedTests(unittest.TestCase):
    def test_producer_binds_reviews_to_active_source_not_initial_source(self) -> None:
        producer = load_producer()
        with tempfile.TemporaryDirectory(prefix="sffs-round155-") as temp_dir:
            repo = Path(temp_dir) / "repo"
            repo.mkdir()
            source = repo / "source.py"
            source.write_text("post-fix source\n", encoding="utf-8")
            active_snapshot = producer.snapshot_files(repo, ["source.py"])
            initial_sha = "0" * 64
            state = {
                "repo_root": str(repo.resolve()),
                "status": "active",
                "source_files": ["source.py"],
                "source_snapshot": active_snapshot,
                "iterations": [
                    {
                        "iteration_id": "r001-initial",
                        "source_sha256": initial_sha,
                        "active_source_sha256": active_snapshot["sha256"],
                    }
                ],
            }
            state_file = repo / "loop-state.json"
            state_file.write_text(json.dumps(state) + "\n", encoding="utf-8")
            p0 = repo / "p0.json"
            p1 = repo / "p1.json"
            p0.write_text("{}\n", encoding="utf-8")
            p1.write_text("{}\n", encoding="utf-8")
            observed_sources: list[str] = []

            def accept_pair(*args, source_sha256: str, **kwargs):
                observed_sources.append(source_sha256)
                return 0, 0

            with mock.patch.object(
                producer, "validate_review_pair", side_effect=accept_pair
            ), mock.patch.object(
                producer,
                "materialize_release_basis",
                side_effect=ReachedRetention("reached retention"),
            ):
                with self.assertRaises(ReachedRetention):
                    producer.produce(
                        repo_root=repo,
                        state_file=state_file,
                        eval_root=repo,
                        p0_review=p0,
                        p1_review=p1,
                        output_dir=repo / "proof",
                    )
            self.assertEqual([active_snapshot["sha256"]], observed_sources)


if __name__ == "__main__":
    unittest.main()
