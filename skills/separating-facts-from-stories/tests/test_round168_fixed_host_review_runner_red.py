#!/usr/bin/env python3
"""Round 168 RED: review evidence must come from the fixed host contract."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HOST_PATH = (
    ROOT
    / "skills"
    / "separating-facts-from-stories"
    / "scripts"
    / "codex_exec_host.py"
)
RUNNER_PATH = HOST_PATH.parent / "host_review_runner.py"
sys.path.insert(0, str(HOST_PATH.parents[1] / "tests"))
from host_execution_fixture import prepare_review_source, write_host_review  # noqa: E402


def load_host():
    spec = importlib.util.spec_from_file_location("round168_host", HOST_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load host runtime")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_runner():
    spec = importlib.util.spec_from_file_location("round168_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load host review runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_minimal_repo(root: Path) -> None:
    (root / "workflows").mkdir(parents=True)
    (root / "README.md").write_text("candidate\n", encoding="utf-8")
    source_files = [
        "README.md",
        "workflows/separating-facts-release-sources.json",
    ]
    (root / "workflows" / "separating-facts-release-sources.json").write_text(
        json.dumps(
            {"schema_version": "1.0.0", "source_files": source_files},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_fake_codex(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

if "--version" in sys.argv:
    print("fixture-codex 1.0")
    raise SystemExit(0)
prompt = sys.stdin.read()
source = re.search(r"^SOURCE_SHA256: ([0-9a-f]{64})$", prompt, re.MULTILINE).group(1)
kind = re.search(r"^ATTESTATION_TYPE: (\\S+)$", prompt, re.MULTILINE).group(1)
payload = {
    "schema_version": "review_payload.v2",
    "attestation_type": kind,
    "source_sha256": source,
    "review_scope": [
        "runtime_semantics",
        "safety_routing",
        "state_integrity",
        "release_evidence",
        "packaging_installation",
        "documentation_claims",
    ],
    "covered_severities": ["P0", "P1"],
    "findings": [],
}
message = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
output = Path(sys.argv[sys.argv.index("--output-last-message") + 1])
output.write_text(message + "\\n", encoding="utf-8")
thread = "thread-" + kind
for event in (
    {"type": "thread.started", "thread_id": thread},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"type": "agent_message", "text": message}},
    {"type": "turn.completed"},
):
    print(json.dumps(event, ensure_ascii=False))
""",
        encoding="utf-8",
    )
    os.chmod(path, 0o700)


class Round168FixedHostReviewRunnerRedTests(unittest.TestCase):
    def test_arbitrary_review_prompt_cwd_and_model_cannot_be_bound(self) -> None:
        host = load_host()
        with tempfile.TemporaryDirectory(prefix="sffs-round168-red-") as temp_dir:
            root = Path(temp_dir).resolve()
            source_sha = prepare_review_source(root)
            report_path, report = write_host_review(
                root,
                "p0_zero",
                source_sha,
                suffix="arbitrary-contract",
            )
            del report_path
            receipt = root / report["host_execution_receipt"]["path"]
            receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
            prompt_path = receipt.parent / "prompt.txt"
            prompt_path.write_text("perform an arbitrary friendly review\n", encoding="utf-8")
            prompt_bytes = prompt_path.read_bytes()
            receipt_payload["bindings"]["prompt_sha256"] = hashlib.sha256(
                prompt_bytes
            ).hexdigest()
            receipt_payload["artifacts"]["prompt"]["sha256"] = hashlib.sha256(
                prompt_bytes
            ).hexdigest()
            receipt_payload["artifacts"]["prompt"]["bytes"] = len(prompt_bytes)
            receipt_payload["command"]["model"] = "arbitrary-friendly-model"
            receipt.write_text(
                json.dumps(receipt_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                host.HostExecutionError,
                "REVIEW_EXECUTION_CONTRACT_MISMATCH",
            ):
                host.derive_review_attestation(
                    receipt_path=receipt,
                    repo_root=root,
                    attestation_type="p0_zero",
                    source_sha256=source_sha,
                )

    def test_fixed_runner_owns_both_review_executions(self) -> None:
        runner = load_runner()
        with tempfile.TemporaryDirectory(prefix="sffs-round168-green-") as temp_dir:
            root = Path(temp_dir).resolve()
            write_minimal_repo(root)
            fake_codex = root / "fixture-codex"
            write_fake_codex(fake_codex)
            result = runner.run_pair(repo_root=root, codex_path=fake_codex)
            self.assertTrue(result["valid"])
            self.assertEqual(0, result["p0_open"])
            self.assertEqual(0, result["reproducible_p1_open"])
            self.assertEqual(
                {"p0_zero", "reproducible_p1_zero"},
                set(result["review_attestations"]),
            )

    def test_public_runner_cli_has_no_execution_contract_overrides(self) -> None:
        runner = load_runner()
        with self.assertRaises(SystemExit):
            runner.parser().parse_args(["run-pair", "--prompt", "friendly.txt"])


if __name__ == "__main__":
    unittest.main()
