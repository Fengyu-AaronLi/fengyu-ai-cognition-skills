from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
CORPUS_PATH = SKILL_DIR / "evals" / "legacy-migration-corpus.json"
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _verified_legacy_artifacts() -> list[tuple[Path, dict, dict]]:
    artifacts: list[tuple[Path, dict, dict]] = []
    corpus = _load(CORPUS_PATH)
    for entry in corpus["entries"]:
        path = SKILL_DIR / entry["artifact"]
        receipt_path = SKILL_DIR / entry["receipt"]
        data = _load(path)
        receipt = _load(receipt_path)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["artifact_sha256"]
        assert casefile.canonical_sha256(data) == entry["casefile_sha256"]
        assert hashlib.sha256(receipt_path.read_bytes()).hexdigest() == entry["receipt_sha256"]
        assert (
            casefile.canonical_sha256(receipt)
            == entry["receipt_canonical_sha256"]
        )
        assert casefile._casefile_version_pair(data) in casefile.MIGRATABLE_VERSION_PAIRS
        assert receipt.get("valid") is True
        assert receipt.get("casefile_sha256") == entry["casefile_sha256"]
        artifacts.append((path, data, receipt))
    return artifacts


class Round137LegacyEpochCorpusRedTests(unittest.TestCase):
    def test_every_hash_bound_verified_legacy_root_uses_its_epoch(self) -> None:
        artifacts = _verified_legacy_artifacts()
        self.assertGreaterEqual(len(artifacts), 10)
        for path, data, receipt in artifacts:
            with self.subTest(path=str(path)):
                self.assertEqual(
                    [],
                    casefile.validate_casefile(
                        data, legacy_receipt=receipt
                    ),
                )

    def test_every_hash_bound_verified_legacy_root_can_start_current_delta(self) -> None:
        artifacts = _verified_legacy_artifacts()
        self.assertGreaterEqual(len(artifacts), 10)
        for path, previous, receipt in artifacts:
            with self.subTest(path=str(path)):
                current = casefile.start_update(
                    previous,
                    "我看到门口多了一把钥匙。",
                    legacy_receipt=receipt,
                )
                self.assertEqual(
                    [],
                    casefile.validate_casefile(
                        current,
                        previous=previous,
                        legacy_receipt=receipt,
                    ),
                )

    def test_all_deterministic_generators_are_delta_scoped(self) -> None:
        _, previous, receipt = next(
            item
            for item in _verified_legacy_artifacts()
            if "with-skill-v30-pre-round124-stale/self-identity-story"
            in str(item[0])
        )
        current = casefile.start_update(
            previous,
            "我看到门口多了一把钥匙。",
            legacy_receipt=receipt,
        )
        original_spans = casefile.generate_source_spans
        original_candidates = casefile.generate_unclassified_observation_candidates
        original_resolutions = casefile.generate_candidate_resolutions
        calls: list[tuple[str, str]] = []

        def spans(input_id: str, text: str, start_index: int = 1):
            calls.append(("spans", input_id))
            self.assertEqual("I2", input_id)
            return original_spans(input_id, text, start_index)

        def candidates(input_id: str, text: str, source_spans, start_counter=1):
            calls.append(("candidates", input_id))
            self.assertEqual("I2", input_id)
            return original_candidates(input_id, text, source_spans, start_counter)

        def resolutions(
            input_id: str,
            text: str,
            source_spans,
            prior_candidates,
            prior_resolutions,
            start_counter=1,
        ):
            calls.append(("resolutions", input_id))
            self.assertEqual("I2", input_id)
            return original_resolutions(
                input_id,
                text,
                source_spans,
                prior_candidates,
                prior_resolutions,
                start_counter,
            )

        with (
            mock.patch.object(casefile, "generate_source_spans", side_effect=spans),
            mock.patch.object(
                casefile,
                "generate_unclassified_observation_candidates",
                side_effect=candidates,
            ),
            mock.patch.object(
                casefile,
                "generate_candidate_resolutions",
                side_effect=resolutions,
            ),
        ):
            self.assertEqual(
                [],
                casefile.validate_casefile(
                    current,
                    previous=previous,
                    legacy_receipt=receipt,
                ),
            )
        self.assertEqual(
            [("spans", "I2"), ("candidates", "I2"), ("resolutions", "I2")],
            calls,
        )


if __name__ == "__main__":
    unittest.main()
