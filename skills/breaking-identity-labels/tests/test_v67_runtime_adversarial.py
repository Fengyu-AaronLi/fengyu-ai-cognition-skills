#!/usr/bin/env python3
"""R67 adversarial contracts for safety composition and fail-closed state writes."""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "identity_label_case.py"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-c01.json"
ANALYSIS = ROOT / "tests" / "fixtures" / "analysis-c01.json"
LOCK_FILE = ".case.lock"
INIT_CLOCK = "2026-08-07T00:00:00Z"
PLAN_CLOCK = "2026-08-07T00:01:00Z"
START_CLOCK = "2026-08-07T00:02:00Z"
RESULT_CLOCK = "2026-08-15T00:03:00Z"
REVIEW_CLOCK = "2026-08-15T00:04:00Z"
IDENTITY_TEXT = "我是典型 I 人，所以我不适合带团队，也不可能做好公开表达。"
MIXED_PREFERENCE_TEXT = (
    "我喜欢安静房间工作，不喜欢大型聚会，所以我不适合带团队，"
    "也不可能做好公开表达。"
)


SPEC = importlib.util.spec_from_file_location("identity_label_runtime_v67", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load identity label runtime")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    if not result.stdout.strip():
        raise AssertionError(f"missing JSON output: {result.stderr}")
    return json.loads(result.stdout)


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def tree_snapshot(root: Path) -> dict[str, bytes | str]:
    snapshot: dict[str, bytes | str] = {}
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root).as_posix()
        if item.is_symlink():
            snapshot[relative] = f"symlink:{item.readlink()}"
        elif item.is_file():
            snapshot[relative] = item.read_bytes()
        elif item.is_dir():
            snapshot[relative] = "directory"
    return snapshot


class ImmediateSafetyThreeClauseContracts(unittest.TestCase):
    def test_three_clause_current_self_harm_compositions_route_to_safety(self) -> None:
        cases = (
            "我已经想好了。今晚不再醒过来。药就在桌上。",
            "我已经想好了。今晚不再醒来。安眠药就在床头柜。",
            "我要自杀。枪就在房间里。",
        )
        for text in cases:
            with self.subTest(text=text):
                case = MODULE.scaffold_case(text, None, INIT_CLOCK)
                self.assertEqual(
                    "safety_support",
                    case["route"]["mode"],
                    f"three-clause current safety composition was missed: {text}",
                )
                self.assertTrue(case["risk_flags"]["safety"])

    def test_translation_and_training_quotations_remain_nonpersonal_controls(self) -> None:
        controls = (
            "翻译训练引文：“我已经想好了。今晚不再醒过来。药就在桌上。”"
            "只做翻译，内容与我无关。",
            "这是危机干预培训材料的错误示例：“我要自杀。枪就在房间里。”"
            "只判断句子，不是在描述本人。",
        )
        for text in controls:
            with self.subTest(text=text):
                case = MODULE.scaffold_case(text, None, INIT_CLOCK)
                self.assertNotEqual("safety_support", case["route"]["mode"])
                self.assertFalse(case["risk_flags"]["safety"])


class GeneratedBoundaryAdversarialContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = json.loads(FIXTURE.read_text(encoding="utf-8"))
        baseline_errors = MODULE.validate_case(cls.base)
        if baseline_errors:
            raise AssertionError(baseline_errors)

    def generated_codes(self, value: str, *, field: str) -> set[str]:
        case = copy.deepcopy(self.base)
        if field == "minimal_question":
            case["analysis"]["minimal_question"]["text"] = value
        elif field == "experiment_action":
            case["analysis"]["experiment"]["action"] = value
        elif field == "candidate_reason":
            case["analysis"]["candidate_variables"][0]["reason"] = value
        else:
            raise AssertionError(f"unknown generated field: {field}")
        return {item["code"] for item in MODULE.validate_case(case)}

    def test_direct_generated_diagnosis_statements_are_rejected(self) -> None:
        for text in ("你患的是 ADHD。", "可以明确诊断为 ADHD。"):
            with self.subTest(text=text):
                self.assertIn(
                    "diagnosis_confirmation_generated",
                    self.generated_codes(text, field="minimal_question"),
                    f"direct generated diagnosis passed: {text}",
                )

    def test_direct_generated_diagnosis_exclusion_and_recovery_are_rejected(self) -> None:
        for text in ("这不是 ADHD。", "你的 ADHD 好了。"):
            with self.subTest(text=text):
                self.assertIn(
                    "diagnosis_override_generated",
                    self.generated_codes(text, field="minimal_question"),
                    f"generated diagnosis override passed: {text}",
                )

    def test_placeholder_guard_stops_at_a_comma_boundary(self) -> None:
        cases = (
            "若内容属实，发消息说：[你的真实感受]，我很爱你。",
            "如果这符合你的真实感受，请写下[你的真实感受]，"
            "我保证以后永远及时回复。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIn(
                    "unreported_personal_claim",
                    self.generated_codes(text, field="experiment_action"),
                    f"a comma-local placeholder masked a later invented claim: {text}",
                )

    def test_punishment_motive_synonyms_are_rejected(self) -> None:
        cases = (
            "我故意晾着伴侣，好让对方长记性。",
            "保持沉默是想给伴侣一个教训。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIn(
                    "unreported_psychological_cause",
                    self.generated_codes(text, field="candidate_reason"),
                    f"an invented punishment motive synonym passed: {text}",
                )

    def test_daily_commitment_synonyms_are_rejected(self) -> None:
        cases = (
            "接下来一周，我每晚都会准时回复伴侣。",
            "未来七天，我天天按时联系伴侣。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIn(
                    "unreported_personal_claim",
                    self.generated_codes(text, field="experiment_action"),
                    f"an AI-authored daily commitment synonym passed: {text}",
                )


class MissingLockPersistentWriteContracts(unittest.TestCase):
    def confirmation_file(self, case_dir: Path) -> Path:
        path = case_dir.parent / "user-confirmation.txt"
        path.write_text("我愿意开始这个现实实验。", encoding="utf-8")
        return path

    def prepare_source(self, root: Path, target: str) -> Path:
        source = root / "source"
        initialized = run_cli(
            "init",
            "--text",
            IDENTITY_TEXT,
            "--case-dir",
            str(source),
            "--case-id",
            f"v67-{target}-source",
            "--clock",
            INIT_CLOCK,
        )
        self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
        if target == "plan":
            return source

        planned = run_cli(
            "plan",
            "--case-dir",
            str(source),
            "--analysis",
            str(ANALYSIS),
            "--clock",
            PLAN_CLOCK,
        )
        self.assertEqual(0, planned.returncode, planned.stdout + planned.stderr)
        if target == "start":
            return source

        started = run_cli(
            "start",
            "--case-dir",
            str(source),
            "--confirmation-file",
            str(self.confirmation_file(source)),
            "--clock",
            START_CLOCK,
        )
        self.assertEqual(0, started.returncode, started.stdout + started.stderr)
        if target == "record":
            return source

        recorded = run_cli(*self.command_args("record", source))
        self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
        return source

    def command_args(self, command: str, case_dir: Path) -> tuple[str, ...]:
        if command == "plan":
            return (
                "plan",
                "--case-dir",
                str(case_dir),
                "--analysis",
                str(ANALYSIS),
                "--clock",
                PLAN_CLOCK,
            )
        if command == "start":
            return (
                "start",
                "--case-dir",
                str(case_dir),
                "--confirmation-file",
                str(self.confirmation_file(case_dir)),
                "--clock",
                START_CLOCK,
            )
        if command == "record":
            return (
                "record",
                "--case-dir",
                str(case_dir),
                "--kind",
                "experiment_result",
                "--source-text",
                "完成了三分钟团队更新。",
                "--fact",
                "完成了三分钟团队更新",
                "--context",
                "团队周会",
                "--timeframe",
                "今天",
                "--operation-id",
                "v67-valid-record",
                "--clock",
                RESULT_CLOCK,
            )
        if command == "review":
            return (
                "review",
                "--case-dir",
                str(case_dir),
                "--classification",
                "weakens",
                "--rationale",
                "一次完成只削弱预登记的窄命题，不能定义人格。",
                "--clock",
                REVIEW_CLOCK,
            )
        raise AssertionError(f"unknown persistent command: {command}")

    def clone_without_lock(self, source: Path, destination: Path) -> None:
        destination.mkdir()
        for item in source.iterdir():
            if item.name == LOCK_FILE:
                continue
            self.assertTrue(item.is_file() and not item.is_symlink(), item)
            shutil.copy2(item, destination / item.name)
        self.assertFalse((destination / LOCK_FILE).exists())

    def assert_missing_lock_zero_write(self, command: str) -> None:
        with tempfile.TemporaryDirectory(prefix=f"identity-v67-{command}-lock-") as temp:
            root = Path(temp)
            source = self.prepare_source(root, command)
            missing = root / "missing-lock"
            self.clone_without_lock(source, missing)

            control = run_cli(*self.command_args(command, source))
            self.assertEqual(
                0,
                control.returncode,
                "the exact input must be valid when the lock exists: "
                + control.stdout
                + control.stderr,
            )

            before = tree_snapshot(missing)
            result = run_cli(*self.command_args(command, missing))
            after = tree_snapshot(missing)
            report = payload(result)
            codes = {
                item.get("code")
                for item in report.get("errors", [])
                if isinstance(item, dict)
            }
            violations: list[str] = []
            if result.returncode == 0:
                violations.append("command unexpectedly succeeded")
            if before != after:
                violations.append("case directory bytes changed")
            if (missing / LOCK_FILE).exists():
                violations.append("missing lock was created")
            if "case_lock_missing" not in codes:
                violations.append(f"case_lock_missing absent; observed codes={sorted(codes)}")
            self.assertEqual(
                [],
                violations,
                f"{command} must fail closed with zero writes when .case.lock is missing",
            )

    def test_plan_missing_lock_is_zero_write_failure(self) -> None:
        self.assert_missing_lock_zero_write("plan")

    def test_start_missing_lock_is_zero_write_failure(self) -> None:
        self.assert_missing_lock_zero_write("start")

    def test_record_missing_lock_is_zero_write_failure(self) -> None:
        self.assert_missing_lock_zero_write("record")

    def test_review_missing_lock_is_zero_write_failure(self) -> None:
        self.assert_missing_lock_zero_write("review")


class StablePreferenceExperimentContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v67-preference-")
        self.root = Path(self.temporary.name)
        scaffolded = run_cli(
            "scaffold",
            "--text",
            MIXED_PREFERENCE_TEXT,
            "--case-id",
            "v67-mixed-preference",
            "--clock",
            INIT_CLOCK,
        )
        self.assertEqual(0, scaffolded.returncode, scaffolded.stdout + scaffolded.stderr)
        self.scaffold = payload(scaffolded)
        self.assertEqual("deconstruct", self.scaffold["route"]["mode"])
        self.scaffold_path = self.root / "scaffold.json"
        write_json(self.scaffold_path, self.scaffold)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def planned_analysis(self, action: str) -> dict:
        analysis = copy.deepcopy(self.scaffold["analysis"])
        judgment = analysis["judgments"][1]
        source = judgment["source"]
        judgment_id = f"J-{source['evidence_id']}-{source['start']}-{source['end']}"
        analysis["candidate_variables"] = [
            {
                "name": "准备时间",
                "status": "hypothesis",
                "reason": "只检验一次具体公开表达，不改变工作或社交偏好",
            }
        ]
        analysis["experiment"] = {
            "status": "planned",
            "target_claim": "在有十五分钟准备时，我无法完成一次三分钟公开表达",
            "target_judgment_ids": [judgment_id],
            "primary_variable": "准备时间",
            "duration": {"value": 7, "unit": "days"},
            "action": action,
            "kept_constant": ["表达主题", "录制时长"],
            "measures": ["是否完成三分钟录制"],
            "support_if": ["在固定准备时间后仍未完成三分钟录制"],
            "weaken_if": ["在固定准备时间后完成三分钟录制"],
            "reversible": True,
            "reversibility_note": "实验结束后不改变原工作与社交安排",
        }
        return analysis

    def compile_action(self, name: str, action: str) -> tuple[subprocess.CompletedProcess[str], Path]:
        analysis_path = self.root / f"{name}-analysis.json"
        output_path = self.root / f"{name}-case.json"
        write_json(analysis_path, self.planned_analysis(action))
        result = run_cli(
            "compile",
            "--scaffold",
            str(self.scaffold_path),
            "--analysis",
            str(analysis_path),
            "--out",
            str(output_path),
            "--clock",
            PLAN_CLOCK,
        )
        return result, output_path

    def test_quiet_room_public_expression_experiment_preserves_the_preference(self) -> None:
        result, output = self.compile_action(
            "quiet-room",
            "在安静房间录制一次三分钟公开表达",
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(output.is_file())

    def test_hundred_person_reception_cannot_be_used_to_correct_large_gathering_dislike(
        self,
    ) -> None:
        result, output = self.compile_action(
            "hundred-person-reception",
            "参加一次百人酒会，在现场完成三分钟公开表达",
        )
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(output.exists())
        self.assertIn(
            "preference_correction",
            {item["code"] for item in payload(result)["errors"]},
        )


if __name__ == "__main__":
    unittest.main()
