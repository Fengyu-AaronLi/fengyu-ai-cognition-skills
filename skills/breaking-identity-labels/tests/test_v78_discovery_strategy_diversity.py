#!/usr/bin/env python3
"""R78 red contracts for within-strategy discovery probe diversity."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISCOVERY = ROOT / "scripts" / "run_blindspot_discovery.py"
SEED = "breaking-identity-labels-r76"
MINIMUM_PROBES = 9
NONCE = re.compile(r"^〔探针\d+〕")


def normalized_probe_body(text: str) -> str:
    """Remove the synthetic nonce before comparing generated probe meaning."""

    normalized = unicodedata.normalize("NFKC", text)
    without_nonce = NONCE.sub("", normalized, count=1)
    return re.sub(r"\s+", "", without_nonce).strip()


def generate_report(output: Path) -> dict:
    completed = subprocess.run(
        [
            sys.executable,
            str(DISCOVERY),
            "--root",
            str(ROOT),
            "--seed",
            SEED,
            "--minimum-probes",
            str(MINIMUM_PROBES),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={"LC_ALL": "C.UTF-8", "PYTHONHASHSEED": "0"},
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    payload = json.loads(output.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError("discovery report must be an object")
    return payload


class DiscoveryStrategyDiversityRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="v78-discovery-diversity-")
        cls.report = generate_report(Path(cls.temporary.name) / "report.json")
        cls.bodies: dict[str, list[str]] = defaultdict(list)
        for probe in cls.report["probes"]:
            cls.bodies[probe["strategy"]].append(normalized_probe_body(probe["input"]))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_minimum_nine_yields_at_least_three_probe_bodies_per_strategy(self) -> None:
        self.assertEqual(MINIMUM_PROBES, self.report["summary"]["probe_count"])
        for strategy in self.report["strategy_inventory"]:
            with self.subTest(strategy=strategy):
                self.assertGreaterEqual(
                    len(self.bodies[strategy]),
                    3,
                    f"{strategy} must receive at least three generated probes",
                )

    def test_nonce_stripped_probe_bodies_are_distinct_within_each_strategy(self) -> None:
        for strategy in self.report["strategy_inventory"]:
            bodies = self.bodies[strategy]
            with self.subTest(strategy=strategy, bodies=bodies):
                self.assertEqual(
                    len(bodies),
                    len(set(bodies)),
                    f"{strategy} repeats a probe body after the synthetic nonce is removed",
                )


if __name__ == "__main__":
    unittest.main()
