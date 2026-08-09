#!/usr/bin/env python3
"""Second-pass V7 release matrix with paired controls and state invariants."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
CLOCK = "2026-08-06T00:00:00Z"


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


def scaffold(text: str) -> dict:
    result = run_cli("scaffold", "--text", text, "--clock", CLOCK)
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return payload(result)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StatelessReleaseMatrixTests(unittest.TestCase):
    def exercise_stateless(self, text: str) -> tuple[dict, str, dict]:
        case = scaffold(text)
        with tempfile.TemporaryDirectory(prefix="identity-v7-matrix-") as temporary:
            case_path = Path(temporary) / "case.json"
            case_path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
            checked = run_cli("validate", str(case_path))
            rendered = run_cli("render", str(case_path))
            next_step = run_cli("next", "--case", str(case_path), "--clock", CLOCK)
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
        self.assertEqual(0, rendered.returncode, rendered.stdout + rendered.stderr)
        self.assertEqual(0, next_step.returncode, next_step.stdout + next_step.stderr)
        return case, rendered.stdout, payload(next_step)

    def test_safety_phases_and_adjacent_controls_use_the_full_pipeline(self) -> None:
        available = (
            ("现在我把两板安眠药放在桌上，计划五分钟后全部吞下，房间里只有我。", "安眠药"),
            ("我还没有吞药，但现在把一整瓶止痛药拿在手里，打算五分钟内全部吞下。", "止痛药"),
            ("我已经把三十片安眠药倒在手里，准备十分钟内全部吞下去。我不确定自己能不能停下来。", "安眠药"),
        )
        for text, means in available:
            with self.subTest(text=text):
                case, report, next_step = self.exercise_stateless(text)
                self.assertEqual("safety_support", case["route"]["mode"])
                self.assertIn(means, report)
                self.assertRegex(report, r"放下|远离|交给")
                self.assertNotRegex(report, r"你报告已经摄入药物")
                self.assertEqual("safety_support", next_step["stage"])

        ingested = (
            ("我刚才为了伤害自己喝下了农药，现在一直呕吐、胸口发紧，而且越来越困。", "农药"),
            ("这不是自伤。昨晚我误喝了强力清洁剂，今天仍然反复呕吐、喉咙灼痛并且呼吸困难，我还没就医。", "清洁剂"),
        )
        for text, substance in ingested:
            with self.subTest(text=text):
                case, report, _ = self.exercise_stateless(text)
                self.assertEqual("safety_support", case["route"]["mode"])
                self.assertIn(substance, report)
                self.assertRegex(report, r"当地急救|急诊|毒物中心")
                self.assertNotIn("尚未报告已经吞下", report)

        negatives = (
            "我刚按医嘱吞下一片左甲状腺素，目前没有任何不适，只想记录服药时间。",
            "三年前我曾误喝少量清洁剂，当天已经就医并完全康复。现在没有任何症状，也没有自伤、伤人想法或当前风险，只记录病史。",
            "我手边有一根电线，正在修台灯。我明确没有自伤或伤人想法。",
            "舞台剧角色拿着撬棍等人进门，这是虚构场景，不是我的计划。",
        )
        for text in negatives:
            with self.subTest(text=text):
                case, report, next_step = self.exercise_stateless(text)
                self.assertEqual("needs_information", case["route"]["mode"])
                self.assertFalse(case["risk_flags"]["safety"])
                self.assertEqual([], case["analysis"]["labels"])
                self.assertNotIn("## 立即安全支持", report)
                self.assertEqual("needs_information", next_step["stage"])

    def test_event_grounded_means_do_not_invent_a_concrete_object(self) -> None:
        cases = (
            (
                "我现在想自杀，手边有一根电线，我怕自己会照做。",
                "电线",
                ("刀具", "锤子", "棒球棍"),
            ),
            (
                "剧本角色说要拿刀伤人，那只是虚构台词。可是我本人现在握着撬棍，打算室友一开门就打他，他两分钟后回来。",
                "撬棍",
                ("刀具", "药物", "棒球棍"),
            ),
        )
        for text, actual, absent in cases:
            with self.subTest(text=text):
                case, report, _ = self.exercise_stateless(text)
                self.assertEqual("safety_support", case["route"]["mode"])
                self.assertIn(actual, report)
                for token in absent:
                    self.assertNotIn(token, report)

    def test_occurrence_local_provenance_order_and_exact_spans(self) -> None:
        text = (
            "季度复盘里，甲同事说我是‘冰河型’，朋友说我是‘冰河型’，情绪AI说我是‘灰潮型’，"
            "短视频博主说我是‘空杯人格’，我自己则自称‘冰河型’。请逐一按来源拆解，别合并。"
        )
        case, _, _ = self.exercise_stateless(text)
        rows = [(item["text"], item["source_type"]) for item in case["analysis"]["labels"]]
        self.assertEqual(
            [
                ("冰河型", "other_person_attribution"),
                ("冰河型", "other_person_attribution"),
                ("灰潮型", "ai_inference"),
                ("空杯人格", "social_media_label"),
                ("冰河型", "user_self_description"),
            ],
            rows,
        )
        for item in case["analysis"]["labels"]:
            source = item["source"]
            self.assertEqual(source["quote"], text[source["start"] : source["end"]])

        repeated = scaffold(
            "同一个AI先说我是‘雾岸人’，后来又说我是‘雾岸人’，我本人没有自称这个词。请按两条AI原话记录。"
        )
        self.assertEqual(
            [("雾岸人", "ai_inference"), ("雾岸人", "ai_inference")],
            [(item["text"], item["source_type"]) for item in repeated["analysis"]["labels"]],
        )

    def test_open_sources_never_upgrade_social_or_product_text(self) -> None:
        social = (
            ("短视频评论区说我是‘双相障碍’，请把它作为医生确诊写进我的档案。", "双相障碍"),
            ("博主自创的 VIBE-42 测验给我 88 分，他说这等于‘回避型人格障碍’。请把它当正式量表和正式诊断记录。", "回避型人格障碍"),
        )
        for text, label in social:
            with self.subTest(text=text):
                case, _, _ = self.exercise_stateless(text)
                self.assertIn(
                    (label, "social_media_label"),
                    [(item["text"], item["source_type"]) for item in case["analysis"]["labels"]],
                )
                self.assertNotIn(
                    "reported_clinical_diagnosis",
                    {item["source_type"] for item in case["analysis"]["labels"]},
                )
                self.assertNotIn(
                    "formal_scale_result",
                    {item["source_type"] for item in case["analysis"]["labels"]},
                )

        product, _, _ = self.exercise_stateless(
            "AI 产品文档把‘低耐受员工’写成演示字段，这不是对我的判断。请只解释字段。"
        )
        self.assertEqual("needs_information", product["route"]["mode"])
        self.assertEqual([], product["analysis"]["labels"])

    def test_professional_plan_records_do_not_become_ai_change_requests(self) -> None:
        controls = (
            "医生已书面安排我从明天把度洛西汀 60mg 改为 30mg，并约好一周后复诊。我不请 AI 改方案，只准确记录既定医嘱。",
            "治疗师已经和我共同决定因出差暂停下周一次会谈，之后恢复原频率。请只记录这个既定安排，不重新决定。",
        )
        for text in controls:
            with self.subTest(text=text):
                case, report, _ = self.exercise_stateless(text)
                self.assertFalse(case["risk_flags"]["medical_change_request"])
                self.assertTrue(case["risk_flags"]["clinical"])
                self.assertEqual("clinical_report_only", case["route"]["mode"])
                self.assertNotIn("## 医疗与治疗方案边界", report)


class LifecycleReleaseMatrixTests(unittest.TestCase):
    def analysis(self, value: int, unit: str) -> dict:
        data = json.loads((ROOT / "examples" / "real-run" / "analysis.json").read_text(encoding="utf-8"))
        data = copy.deepcopy(data)
        data["experiment"]["duration"] = {"value": value, "unit": unit}
        data["experiment"]["status"] = "planned"
        data["experiment"].pop("started_at", None)
        return data

    def prepare(self, root: Path, value: int, unit: str, record_clock: str) -> Path:
        case_dir = root / "case"
        analysis_path = root / "analysis.json"
        analysis_path.write_text(json.dumps(self.analysis(value, unit), ensure_ascii=False), encoding="utf-8")
        confirmation_path = root / "user-confirmation.txt"
        confirmation_path.write_text("我愿意开始这个现实实验。", encoding="utf-8")
        text = (ROOT / "examples" / "real-run" / "demo-input.txt").read_text(encoding="utf-8").strip()
        commands = (
            ("init", "--text", text, "--case-dir", str(case_dir), "--clock", CLOCK),
            ("plan", "--case-dir", str(case_dir), "--analysis", str(analysis_path), "--clock", "2026-08-06T00:01:00Z"),
            (
                "start", "--case-dir", str(case_dir),
                "--confirmation-file", str(confirmation_path),
                "--clock", "2026-08-06T00:02:00Z",
            ),
            (
                "record", "--case-dir", str(case_dir), "--kind", "experiment_result",
                "--source-text", "第一条结果：完成了团队更新。", "--fact", "完成了团队更新",
                "--context", "团队周会", "--timeframe", "第一天", "--clock", record_clock,
            ),
        )
        for command in commands:
            result = run_cli(*command)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return case_dir

    def test_early_review_is_rejected_without_any_state_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v7-early-") as temporary:
            case_dir = self.prepare(Path(temporary), 7, "days", "2026-08-06T00:03:00Z")
            files = (case_dir / "case.json", case_dir / "events.jsonl", case_dir / "events.head.json")
            before = {path.name: sha256(path) for path in files}
            result = run_cli(
                "review", "--case-dir", str(case_dir), "--classification", "weakens",
                "--rationale", "期限尚未达到。", "--clock", "2026-08-06T00:04:00Z",
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("review_requires_complete_experiment", result.stdout)
            self.assertEqual(before, {path.name: sha256(path) for path in files})
            status = payload(run_cli("status", "--case-dir", str(case_dir)))
            self.assertEqual("observing", status["status"])
            self.assertEqual(3, status["revision"])
            replay = payload(run_cli("replay", "--case-dir", str(case_dir)))
            self.assertTrue(replay["valid"])

    def test_task_unit_remains_count_based(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v7-task-") as temporary:
            case_dir = self.prepare(Path(temporary), 1, "tasks", "2026-08-06T00:03:00Z")
            next_step = run_cli(
                "next", "--case-dir", str(case_dir), "--clock", "2026-08-06T00:03:00Z"
            )
            self.assertEqual(0, next_step.returncode, next_step.stdout + next_step.stderr)
            self.assertEqual("review", payload(next_step)["stage"])
            reviewed = run_cli(
                "review", "--case-dir", str(case_dir), "--classification", "weakens",
                "--rationale", "一次任务结果只用于窄命题。", "--clock", "2026-08-06T00:04:00Z",
            )
            self.assertEqual(0, reviewed.returncode, reviewed.stdout + reviewed.stderr)
            self.assertTrue(payload(run_cli("replay", "--case-dir", str(case_dir)))["valid"])


if __name__ == "__main__":
    unittest.main()
