#!/usr/bin/env python3
"""V8 red tests for workflow clocks, atomicity and replay time invariants."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
DEMO_TEXT = (ROOT / "examples" / "real-run" / "demo-input.txt").read_text(encoding="utf-8").strip()
BASE_ANALYSIS = json.loads((ROOT / "examples" / "real-run" / "analysis.json").read_text(encoding="utf-8"))
T0 = "2026-08-06T12:00:00Z"
T1 = "2026-08-06T12:01:00Z"
T2 = "2026-08-06T12:02:00Z"
T3 = "2026-08-06T12:03:00Z"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


def file_hashes(case_dir: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((case_dir / name).read_bytes()).hexdigest()
        for name in ("case.json", "events.jsonl", "events.head.json")
        if (case_dir / name).exists()
    }


def canonical_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def make_analysis(unit: str = "tasks", value: int = 1) -> dict:
    analysis = copy.deepcopy(BASE_ANALYSIS)
    analysis["experiment"]["duration"] = {"value": value, "unit": unit}
    analysis["experiment"]["status"] = "planned"
    analysis["experiment"].pop("started_at", None)
    return analysis


def require_success(test: unittest.TestCase, result: subprocess.CompletedProcess[str]) -> None:
    test.assertEqual(0, result.returncode, result.stdout + result.stderr)


def confirmation_file(root: Path) -> Path:
    path = root / "user-confirmation.txt"
    path.write_text("我愿意开始这个现实实验。", encoding="utf-8")
    return path


def prepare_case(
    test: unittest.TestCase,
    root: Path,
    state: str,
    *,
    unit: str = "tasks",
    value: int = 1,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    case_dir = root / "case"
    analysis_path = root / "analysis.json"
    analysis_path.write_text(json.dumps(make_analysis(unit, value), ensure_ascii=False), encoding="utf-8")
    require_success(
        test,
        run_cli("init", "--text", DEMO_TEXT, "--case-dir", str(case_dir), "--clock", T0),
    )
    if state == "drafted":
        return case_dir
    require_success(
        test,
        run_cli("plan", "--case-dir", str(case_dir), "--analysis", str(analysis_path), "--clock", T1),
    )
    if state == "planned":
        return case_dir
    require_success(
        test,
        run_cli(
            "start",
            "--case-dir",
            str(case_dir),
            "--confirmation-file",
            str(confirmation_file(root)),
            "--clock",
            T2,
        ),
    )
    if state == "observing":
        return case_dir
    require_success(
        test,
        run_cli(
            "record",
            "--case-dir",
            str(case_dir),
            "--kind",
            "experiment_result",
            "--source-text",
            "结果：完成了可修改的分工初版。",
            "--fact",
            "完成了可修改的分工初版",
            "--context",
            "纸面分工任务",
            "--timeframe",
            "第一次",
            "--clock",
            T3,
        ),
    )
    return case_dir


def rehash_history(case_dir: Path) -> None:
    events_path = case_dir / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    previous = None
    for event in events:
        event["previous_event_sha256"] = previous
        event["snapshot_sha256"] = canonical_digest(event["snapshot"])
        event.pop("event_sha256", None)
        event["event_sha256"] = canonical_digest(event)
        previous = event["event_sha256"]
    events_path.write_text(
        "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    latest = events[-1]
    (case_dir / "case.json").write_text(
        json.dumps(latest["snapshot"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    head = {
        "schema_version": "1.0",
        "case_id": latest["snapshot"]["case_id"],
        "event_count": len(events),
        "latest_revision": latest["snapshot"]["revision"],
        "latest_event_sha256": latest["event_sha256"],
        "latest_snapshot_sha256": latest["snapshot_sha256"],
        "updated_at": latest["recorded_at"],
    }
    (case_dir / "events.head.json").write_text(
        json.dumps(head, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class ClockAdmissionAndAtomicityTests(unittest.TestCase):
    def assert_clock_failure(self, result: subprocess.CompletedProcess[str], expected_code: str) -> None:
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn(expected_code, {item["code"] for item in payload(result)["errors"]})

    def test_scaffold_and_init_reject_invalid_or_naive_clocks_before_writing(self) -> None:
        for clock, code in (("not-a-clock", "clock_invalid"), ("2026-08-06T12:00:00", "clock_requires_timezone")):
            with self.subTest(command="scaffold", clock=clock):
                result = run_cli("scaffold", "--text", DEMO_TEXT, "--clock", clock)
                self.assert_clock_failure(result, code)
            with self.subTest(command="init", clock=clock):
                with tempfile.TemporaryDirectory(prefix="identity-v8-clock-init-") as temporary:
                    case_dir = Path(temporary) / "case"
                    result = run_cli("init", "--text", DEMO_TEXT, "--case-dir", str(case_dir), "--clock", clock)
                    self.assert_clock_failure(result, code)
                    self.assertFalse(case_dir.exists(), "invalid init must not leave a directory or partial files")

    def test_every_persistent_command_rejects_bad_clock_without_state_change(self) -> None:
        for clock, code in (("not-a-clock", "clock_invalid"), ("2026-08-06T12:04:00", "clock_requires_timezone")):
            commands = (
                ("plan", "drafted"),
                ("start", "planned"),
                ("record", "observing"),
                ("review", "recorded"),
            )
            for command, state in commands:
                with self.subTest(command=command, clock=clock):
                    with tempfile.TemporaryDirectory(prefix=f"identity-v8-clock-{command}-") as temporary:
                        root = Path(temporary)
                        case_dir = prepare_case(self, root, state)
                        before = file_hashes(case_dir)
                        if command == "plan":
                            analysis_path = root / "bad-analysis.json"
                            analysis_path.write_text(json.dumps(make_analysis(), ensure_ascii=False), encoding="utf-8")
                            result = run_cli(
                                "plan", "--case-dir", str(case_dir), "--analysis", str(analysis_path), "--clock", clock
                            )
                        elif command == "start":
                            result = run_cli(
                                "start",
                                "--case-dir",
                                str(case_dir),
                                "--confirmation-file",
                                str(confirmation_file(root)),
                                "--clock",
                                clock,
                            )
                        elif command == "record":
                            result = run_cli(
                                "record", "--case-dir", str(case_dir), "--kind", "experiment_result",
                                "--source-text", "结果：完成任务。", "--fact", "完成任务",
                                "--context", "纸面任务", "--timeframe", "当前", "--clock", clock,
                            )
                        else:
                            result = run_cli(
                                "review", "--case-dir", str(case_dir), "--classification", "weakens",
                                "--rationale", "只复核预登记窄命题。", "--clock", clock,
                            )
                        self.assert_clock_failure(result, code)
                        self.assertEqual(before, file_hashes(case_dir))
                        self.assertTrue(payload(run_cli("replay", "--case-dir", str(case_dir)))["valid"])

    def test_next_rejects_bad_elapsed_clock_but_remains_read_only(self) -> None:
        for clock, code in (("not-a-clock", "clock_invalid"), ("2026-08-06T13:03:00", "clock_requires_timezone")):
            with self.subTest(clock=clock):
                with tempfile.TemporaryDirectory(prefix="identity-v8-next-clock-") as temporary:
                    case_dir = prepare_case(self, Path(temporary), "recorded", unit="hours", value=1)
                    before = file_hashes(case_dir)
                    result = run_cli("next", "--case-dir", str(case_dir), "--clock", clock)
                    self.assert_clock_failure(result, code)
                    self.assertEqual(before, file_hashes(case_dir))

    def test_persistent_event_clocks_are_nondecreasing_in_utc(self) -> None:
        attacks = (
            ("plan", "drafted", "2026-08-06T11:59:59Z"),
            ("start", "planned", "2026-08-06T12:00:59Z"),
            ("record", "observing", "2026-08-06T12:01:59Z"),
            ("review", "recorded", "2026-08-06T12:02:59Z"),
        )
        for command, state, clock in attacks:
            with self.subTest(command=command):
                with tempfile.TemporaryDirectory(prefix=f"identity-v8-reverse-{command}-") as temporary:
                    root = Path(temporary)
                    case_dir = prepare_case(self, root, state)
                    before = file_hashes(case_dir)
                    if command == "plan":
                        analysis_path = root / "analysis-reverse.json"
                        analysis_path.write_text(json.dumps(make_analysis(), ensure_ascii=False), encoding="utf-8")
                        result = run_cli(
                            "plan", "--case-dir", str(case_dir), "--analysis", str(analysis_path), "--clock", clock
                        )
                    elif command == "start":
                        result = run_cli(
                            "start",
                            "--case-dir",
                            str(case_dir),
                            "--confirmation-file",
                            str(confirmation_file(root)),
                            "--clock",
                            clock,
                        )
                    elif command == "record":
                        result = run_cli(
                            "record", "--case-dir", str(case_dir), "--kind", "experiment_result",
                            "--source-text", "结果：完成第二项。", "--fact", "完成第二项",
                            "--context", "纸面任务", "--timeframe", "当前", "--clock", clock,
                        )
                    else:
                        result = run_cli(
                            "review", "--case-dir", str(case_dir), "--classification", "weakens",
                            "--rationale", "只复核预登记窄命题。", "--clock", clock,
                        )
                    self.assert_clock_failure(result, "clock_out_of_order")
                    self.assertEqual(before, file_hashes(case_dir))

    def test_equal_instants_with_different_offsets_are_allowed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v8-equal-clock-") as temporary:
            root = Path(temporary)
            case_dir = root / "case"
            analysis_path = root / "analysis.json"
            analysis_path.write_text(json.dumps(make_analysis(), ensure_ascii=False), encoding="utf-8")
            require_success(
                self,
                run_cli("init", "--text", DEMO_TEXT, "--case-dir", str(case_dir), "--clock", "2026-08-06T10:00:00+10:00"),
            )
            require_success(
                self,
                run_cli(
                    "plan", "--case-dir", str(case_dir), "--analysis", str(analysis_path),
                    "--clock", "2026-08-06T00:00:00Z",
                ),
            )
            self.assertTrue(payload(run_cli("replay", "--case-dir", str(case_dir)))["valid"])


class ReplayTimeInvariantTests(unittest.TestCase):
    def assert_replay_code(self, case_dir: Path, code: str) -> None:
        result = run_cli("replay", "--case-dir", str(case_dir))
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn(code, {item["code"] for item in payload(result)["errors"]})

    def test_replay_rejects_rehashed_invalid_and_reverse_event_clocks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v8-replay-time-") as temporary:
            root = Path(temporary)
            baseline = prepare_case(self, root / "baseline", "recorded")

            invalid = root / "invalid"
            shutil.copytree(baseline, invalid)
            events = [json.loads(line) for line in (invalid / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            events[1]["recorded_at"] = "not-a-clock"
            events[1]["snapshot"]["updated_at"] = "not-a-clock"
            (invalid / "events.jsonl").write_text(
                "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events),
                encoding="utf-8",
            )
            rehash_history(invalid)
            self.assert_replay_code(invalid, "event_clock_invalid")

            reverse = root / "reverse"
            shutil.copytree(baseline, reverse)
            events = [json.loads(line) for line in (reverse / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            events[2]["recorded_at"] = "2026-08-06T12:00:30Z"
            events[2]["snapshot"]["updated_at"] = "2026-08-06T12:00:30Z"
            events[2]["snapshot"]["analysis"]["experiment"]["started_at"] = "2026-08-06T12:00:30Z"
            (reverse / "events.jsonl").write_text(
                "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events),
                encoding="utf-8",
            )
            rehash_history(reverse)
            self.assert_replay_code(reverse, "event_clock_out_of_order")

    def test_replay_binds_snapshot_and_new_evidence_times_to_the_event(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v8-replay-bind-") as temporary:
            root = Path(temporary)
            baseline = prepare_case(self, root / "baseline", "recorded")

            snapshot_mismatch = root / "snapshot"
            shutil.copytree(baseline, snapshot_mismatch)
            events = [json.loads(line) for line in (snapshot_mismatch / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            events[-1]["snapshot"]["updated_at"] = "2026-08-06T12:03:01Z"
            (snapshot_mismatch / "events.jsonl").write_text(
                "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events),
                encoding="utf-8",
            )
            rehash_history(snapshot_mismatch)
            self.assert_replay_code(snapshot_mismatch, "timestamp_binding_mismatch")

            evidence_mismatch = root / "evidence"
            shutil.copytree(baseline, evidence_mismatch)
            events = [json.loads(line) for line in (evidence_mismatch / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            events[-1]["snapshot"]["evidence"][-1]["recorded_at"] = "2026-08-06T12:03:01Z"
            (evidence_mismatch / "events.jsonl").write_text(
                "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events),
                encoding="utf-8",
            )
            rehash_history(evidence_mismatch)
            self.assert_replay_code(evidence_mismatch, "timestamp_binding_mismatch")


if __name__ == "__main__":
    unittest.main()
