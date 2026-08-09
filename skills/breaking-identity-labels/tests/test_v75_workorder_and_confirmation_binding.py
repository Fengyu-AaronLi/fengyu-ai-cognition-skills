#!/usr/bin/env python3
"""V75 red contracts for public judgment IDs and scoped start confirmation."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
VERSION = ROOT / "VERSION"
VALID_ANALYSIS = ROOT / "tests" / "fixtures" / "analysis-c01.json"
USER_TEXT = "我是典型 I 人，所以我不适合带团队，也不可能做好公开表达。"
TARGET_ID_PATTERN = re.compile(r"^J-E[0-9]{3}-[0-9]+-[0-9]+$")


def run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def json_stdout(result: subprocess.CompletedProcess[str]) -> dict:
    if not result.stdout.strip():
        raise AssertionError(
            f"expected JSON stdout; exit={result.returncode}; stderr={result.stderr.strip()}"
        )
    return json.loads(result.stdout)


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def snapshot_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def rehash_event_chain(case_dir: Path, events: list[dict]) -> None:
    previous_hash: str | None = None
    for event in events:
        event["previous_event_sha256"] = previous_hash
        event["snapshot_sha256"] = canonical_sha256(event["snapshot"])
        event["event_sha256"] = canonical_sha256(
            {key: value for key, value in event.items() if key != "event_sha256"}
        )
        previous_hash = event["event_sha256"]

    (case_dir / "events.jsonl").write_text(
        "\n".join(
            json.dumps(event, ensure_ascii=False, sort_keys=True) for event in events
        )
        + "\n",
        encoding="utf-8",
    )
    head_path = case_dir / "events.head.json"
    head = json.loads(head_path.read_text(encoding="utf-8"))
    head["event_count"] = len(events)
    head["latest_revision"] = events[-1]["revision"]
    head["latest_event_sha256"] = events[-1]["event_sha256"]
    head["latest_snapshot_sha256"] = events[-1]["snapshot_sha256"]
    head_path.write_text(
        json.dumps(head, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class RuntimeFixture(unittest.TestCase):
    def scaffold(self, root: Path) -> Path:
        scaffold_path = root / "scaffold.json"
        result = run_cli(
            "scaffold",
            "--text",
            USER_TEXT,
            "--out",
            str(scaffold_path),
            "--case-id",
            "CASE-V75-WORKORDER",
            "--clock",
            "2026-08-07T02:00:00Z",
            cwd=root,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return scaffold_path

    def prepare(self, root: Path, scaffold: Path, name: str) -> Path:
        analysis_path = root / name
        result = run_cli(
            "prepare-analysis",
            "--scaffold",
            str(scaffold),
            "--out",
            str(analysis_path),
            cwd=root,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return analysis_path

    def planned_case(self, root: Path) -> Path:
        case_dir = root / "case"
        initialized = run_cli(
            "init",
            "--text",
            USER_TEXT,
            "--case-dir",
            str(case_dir),
            "--case-id",
            "CASE-V75-CONFIRMATION",
            "--clock",
            "2026-08-07T03:00:00Z",
            cwd=root,
        )
        self.assertEqual(
            0, initialized.returncode, initialized.stdout + initialized.stderr
        )
        planned = run_cli(
            "plan",
            "--case-dir",
            str(case_dir),
            "--analysis",
            str(VALID_ANALYSIS),
            "--expected-revision",
            "0",
            "--clock",
            "2026-08-07T03:01:00Z",
            cwd=root,
        )
        self.assertEqual(0, planned.returncode, planned.stdout + planned.stderr)
        return case_dir

    def start_with_valid_words(self, root: Path, case_dir: Path) -> None:
        confirmation = root / "user-confirmation.txt"
        confirmation.write_text(
            "我确认愿意开始这一个七天的小规模实验。", encoding="utf-8"
        )
        started = run_cli(
            "start",
            "--case-dir",
            str(case_dir),
            "--confirmation-file",
            str(confirmation),
            "--expected-revision",
            "1",
            "--clock",
            "2026-08-07T03:02:00Z",
            cwd=root,
        )
        self.assertEqual(0, started.returncode, started.stdout + started.stderr)


class AnalysisWorkOrderTargetIdTests(RuntimeFixture):
    def test_prepare_exposes_one_stable_copyable_target_id_per_judgment(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v75-target-ids-") as temp:
            root = Path(temp)
            scaffold_path = self.scaffold(root)
            first_path = self.prepare(root, scaffold_path, "analysis-first.json")
            second_path = self.prepare(root, scaffold_path, "analysis-second.json")
            scaffold = json.loads(scaffold_path.read_text(encoding="utf-8"))
            first = json.loads(first_path.read_text(encoding="utf-8"))
            second = json.loads(second_path.read_text(encoding="utf-8"))

            self.assertGreater(len(first["judgments"]), 0)
            first_ids: list[str] = []
            second_ids: list[str] = []
            evidence_by_id = {item["id"]: item for item in scaffold["evidence"]}
            for index, judgment in enumerate(first["judgments"]):
                self.assertIn(
                    "target_id",
                    judgment,
                    f"judgment {index} forces the agent to reconstruct a hidden ID",
                )
                target_id = judgment["target_id"]
                self.assertIsInstance(target_id, str)
                self.assertRegex(target_id, TARGET_ID_PATTERN)
                source = judgment["source"]
                expected = f"J-{source['evidence_id']}-{source['start']}-{source['end']}"
                self.assertEqual(expected, target_id)
                evidence_text = evidence_by_id[source["evidence_id"]]["text"]
                self.assertEqual(
                    source["quote"], evidence_text[source["start"] : source["end"]]
                )
                first_ids.append(target_id)

            for index, judgment in enumerate(second["judgments"]):
                self.assertIn("target_id", judgment, f"judgment {index} has no public ID")
                second_ids.append(judgment["target_id"])
            self.assertEqual(first_ids, second_ids)
            self.assertEqual(len(first_ids), len(set(first_ids)))

    def test_compile_accepts_the_public_target_id_without_reconstruction(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v75-compile-id-") as temp:
            root = Path(temp)
            scaffold_path = self.scaffold(root)
            analysis_path = self.prepare(root, scaffold_path, "analysis.json")
            analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
            self.assertIn(
                "target_id",
                analysis["judgments"][0],
                "prepare-analysis did not expose the value compile asks the agent to cite",
            )
            public_id = analysis["judgments"][0]["target_id"]
            fixture = json.loads(VALID_ANALYSIS.read_text(encoding="utf-8"))
            for field in (
                "counterexamples",
                "candidate_variables",
                "unknowns",
                "minimal_question",
                "reserved_judgments",
            ):
                analysis[field] = copy.deepcopy(fixture[field])
            analysis["experiment"] = copy.deepcopy(fixture["experiment"])
            analysis["experiment"]["target_judgment_ids"] = [public_id]
            analysis_path.write_text(
                json.dumps(analysis, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            case_path = root / "case.json"
            compiled = run_cli(
                "compile",
                "--scaffold",
                str(scaffold_path),
                "--analysis",
                str(analysis_path),
                "--out",
                str(case_path),
                "--clock",
                "2026-08-07T02:01:00Z",
                cwd=root,
            )
            self.assertEqual(
                0,
                compiled.returncode,
                "compile rejected the exact target_id published by prepare-analysis:\n"
                + compiled.stdout
                + compiled.stderr,
            )
            case = json.loads(case_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [public_id], case["analysis"]["experiment"]["target_judgment_ids"]
            )


class ScopedExperimentConfirmationTests(RuntimeFixture):
    def test_start_rejects_unrelated_nonempty_version_bytes_without_writing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v75-unrelated-confirm-") as temp:
            root = Path(temp)
            case_dir = self.planned_case(root)
            before = snapshot_files(case_dir)
            started = run_cli(
                "start",
                "--case-dir",
                str(case_dir),
                "--confirmation-file",
                str(VERSION),
                "--expected-revision",
                "1",
                "--clock",
                "2026-08-07T03:02:00Z",
                cwd=root,
            )
            self.assertNotEqual(
                0,
                started.returncode,
                "any non-empty file, including VERSION, is currently treated as consent",
            )
            self.assertIn(
                "user_confirmation_intent_mismatch",
                {item["code"] for item in json_stdout(started)["errors"]},
            )
            self.assertEqual(before, snapshot_files(case_dir))

    def test_start_event_binds_the_exact_pre_start_case_revision_and_experiment(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v75-confirm-scope-") as temp:
            root = Path(temp)
            case_dir = self.planned_case(root)
            pre_start = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
            self.start_with_valid_words(root, case_dir)
            events = [
                json.loads(line)
                for line in (case_dir / "events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            binding = events[-1].get("user_confirmation")
            self.assertIsInstance(binding, dict)
            assert isinstance(binding, dict)
            self.assertEqual(pre_start["case_id"], binding.get("case_id"))
            self.assertEqual(
                pre_start["revision"], binding.get("pre_start_revision")
            )
            self.assertEqual(
                canonical_sha256(pre_start["analysis"]["experiment"]),
                binding.get("experiment_sha256"),
            )

    def test_replay_rejects_a_rehashed_confirmation_scope_tamper(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v75-confirm-tamper-") as temp:
            root = Path(temp)
            case_dir = self.planned_case(root)
            self.start_with_valid_words(root, case_dir)
            events = [
                json.loads(line)
                for line in (case_dir / "events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            pre_start = events[-2]["snapshot"]
            binding = events[-1]["user_confirmation"]
            binding["case_id"] = pre_start["case_id"]
            binding["pre_start_revision"] = pre_start["revision"]
            binding["experiment_sha256"] = "0" * 64
            rehash_event_chain(case_dir, events)

            replayed = run_cli("replay", "--case-dir", str(case_dir), cwd=root)
            self.assertNotEqual(
                0,
                replayed.returncode,
                "re-hashing the event chain legitimized a confirmation bound to another experiment",
            )
            self.assertIn(
                "event_confirmation_scope_mismatch",
                {item["code"] for item in json_stdout(replayed)["errors"]},
            )


class ConfirmationDocumentationBoundaryTests(unittest.TestCase):
    def test_docs_do_not_equate_file_bytes_with_authenticated_human_consent(self) -> None:
        documents = [
            ROOT / "SKILL.md",
            ROOT / "README.md",
            ROOT / "docs" / "quickstart.md",
            ROOT / "docs" / "acceptance.md",
        ]
        corpus = "\n".join(path.read_text(encoding="utf-8") for path in documents)
        for unsupported_claim in (
            "已认证用户同意",
            "已验证真人同意",
            "authenticated user consent",
            "verified human consent",
        ):
            self.assertNotIn(unsupported_claim, corpus.lower())

        explicit_boundary = re.compile(
            r"(?:文件|字节|artifact|event).{0,120}"
            r"(?:绑定|哈希|hash).{0,120}"
            r"(?:不等于|不能证明|不构成|does not|cannot).{0,120}"
            r"(?:真实用户|用户本人|真人|人类身份|human identity|authenticated consent)",
            flags=re.IGNORECASE | re.DOTALL,
        )
        self.assertIsNotNone(
            explicit_boundary.search(corpus),
            "docs must say that file/event binding cannot authenticate a real human or consent",
        )


if __name__ == "__main__":
    unittest.main()
