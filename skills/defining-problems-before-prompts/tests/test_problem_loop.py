from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_dpbp_runtime import canonical_json, gate_receipt, valid_define_spec, valid_high_risk_spec


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "dpbp"
HIGH_RISK_OUTCOME = "比较留下谈条件和离开的可逆路径"
HIGH_RISK_CRITERION = "完成两条路径的比较，并记录排除继续失眠这一健康代价。"
HIGH_RISK_Q3 = f"我要先{HIGH_RISK_OUTCOME}；成功标准是：{HIGH_RISK_CRITERION}"


def evidence(source_id: str, text: str, quote: str | None = None) -> dict[str, object]:
    selected = text if quote is None else quote
    start = text.index(selected)
    return {
        "source_id": source_id,
        "start": start,
        "end": start + len(selected),
        "quote": selected,
    }


def success_criterion(
    value: str,
    source_id: str,
    text: str,
    quote: str | None = None,
) -> dict[str, object]:
    return {"value": value, "sources": [evidence(source_id, text, quote or value)]}


class ProblemDefinitionLoopContract(unittest.TestCase):
    maxDiff = None

    def run_cli(self, *args: str, payload: object | str = "") -> subprocess.CompletedProcess[str]:
        raw = payload if isinstance(payload, str) else canonical_json(payload)
        return subprocess.run(
            [str(CLI), *args],
            input=raw,
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
        )

    def parsed(self, result: subprocess.CompletedProcess[str]) -> dict[str, object]:
        self.assertEqual("", result.stderr)
        value = json.loads(result.stdout)
        self.assertIsInstance(value, dict)
        return value

    def start(self, state_path: Path, spec: dict[str, object], max_rounds: int = 2) -> dict[str, object]:
        result = self.run_cli(
            "start",
            "--state",
            str(state_path),
            "--max-rounds",
            str(max_rounds),
            payload=spec,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return self.parsed(result)

    def answer(
        self,
        state_path: Path,
        *,
        answer_id: str,
        question_id: str,
        answer: str,
        expected_revision: int,
    ) -> dict[str, object]:
        result = self.run_cli(
            "resume",
            "--state",
            str(state_path),
            payload={
                "answer_id": answer_id,
                "question_id": question_id,
                "answer": answer,
                "expected_revision": expected_revision,
            },
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return self.parsed(result)

    def answer_define_round(self, state_path: Path, start_revision: int = 1, prefix: str = "a") -> dict[str, object]:
        criterion = "同一流程的返工工单记录出现可复核下降。"
        answers = (
            ("q1", "减少访谈记录返工。"),
            ("q2", "访谈记录整理步骤最容易返工。"),
            ("q3", f"我确认成功标准是：{criterion}"),
        )
        state: dict[str, object] = {}
        for offset, (question_id, text) in enumerate(answers):
            state = self.answer(
                state_path,
                answer_id=f"{prefix}{offset + 1}",
                question_id=question_id,
                answer=text,
                expected_revision=start_revision + offset,
            )
        return state

    def resolved_define_spec(self) -> dict[str, object]:
        spec = valid_define_spec()
        answer = "减少访谈记录返工。"
        criterion = "同一流程的返工工单记录出现可复核下降。"
        criterion_answer = f"我确认成功标准是：{criterion}"
        spec["status"] = "confirmed"
        spec["desired_outcome"] = {
            "status": "stated",
            "value": "减少访谈记录返工",
            "sources": [evidence("answer:a1", answer, "减少访谈记录返工")],
        }
        spec["decisive_unknowns"] = []
        spec["questions"] = []
        spec["success_evidence"] = [
            success_criterion(criterion, "answer:a3", criterion_answer)
        ]
        spec["rewritten_problem"] = "怎样在既定访谈整理流程中减少可复核的返工？"
        return spec

    def ready_high_risk_state(
        self,
        state_path: Path,
        *,
        prefix: str,
        tradeoff_count: int = 1,
    ) -> dict[str, object]:
        spec = valid_high_risk_spec()
        if tradeoff_count == 2:
            spec["value_tradeoffs"].append(
                {
                    "value": "立即离开与先谈条件后再评估如何取舍。",
                    "decision_owner": "user",
                }
            )
        self.start(state_path, spec)
        answers = (
            ("q1", "现金可以覆盖六个月，另有一个替代岗位。"),
            ("q2", "失眠是不能继续承受的健康损失。"),
            ("q3", HIGH_RISK_Q3),
        )
        for offset, (question_id, answer) in enumerate(answers):
            self.answer(
                state_path,
                answer_id=f"{prefix}-{offset + 1}",
                question_id=question_id,
                answer=answer,
                expected_revision=1 + offset,
            )
        resolved = copy.deepcopy(spec)
        resolved["status"] = "confirmed"
        resolved["desired_outcome"] = {
            "status": "stated",
            "value": HIGH_RISK_OUTCOME,
            "sources": [
                evidence(
                    f"answer:{prefix}-3",
                    answers[2][1],
                    HIGH_RISK_OUTCOME,
                )
            ],
        }
        resolved["decisive_unknowns"] = []
        resolved["questions"] = []
        resolved["success_evidence"] = [
            success_criterion(
                HIGH_RISK_CRITERION,
                f"answer:{prefix}-3",
                answers[2][1],
            )
        ]
        advanced = self.run_cli(
            "advance",
            "--state",
            str(state_path),
            payload={
                "advance_id": f"{prefix}-ready",
                "expected_revision": 4,
                "spec": resolved,
            },
        )
        self.assertEqual(0, advanced.returncode, advanced.stdout + advanced.stderr)
        ready = self.parsed(advanced)
        self.assertEqual("awaiting_user_decision", ready["phase"])
        return ready

    def test_answer_evidence_can_advance_to_a_terminal_problem_definition(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            started = self.start(state_path, valid_define_spec())
            self.assertEqual("awaiting_answers", started["phase"])
            answered = self.answer_define_round(state_path)
            self.assertEqual("needs_reassessment", answered["phase"])

            result = self.run_cli(
                "advance",
                "--state",
                str(state_path),
                payload={
                    "advance_id": "advance-1",
                    "expected_revision": 4,
                    "spec": self.resolved_define_spec(),
                },
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            terminal = self.parsed(result)
            self.assertEqual("ready_for_answer", terminal["phase"])
            self.assertEqual("problem_defined", terminal["stop_reason"])
            self.assertEqual([], terminal["convergence"]["unresolved_unknown_ids"])
            self.assertEqual(5, terminal["revision"])

    def test_answer_source_tampering_and_unknown_sources_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            self.start(state_path, valid_define_spec())
            self.answer_define_round(state_path)
            tampered = self.resolved_define_spec()
            tampered["desired_outcome"]["sources"][0]["quote"] = "用户没有回答过的目标"
            result = self.run_cli(
                "advance",
                "--state",
                str(state_path),
                payload={"advance_id": "bad-span", "expected_revision": 4, "spec": tampered},
            )
            self.assertEqual(5, result.returncode)
            codes = [item["code"] for item in self.parsed(result)["errors"]]
            self.assertIn("EVIDENCE_SPAN_MISMATCH", codes)

    def test_confirmed_requires_state_and_cannot_keep_decisive_unknowns(self) -> None:
        confirmed = valid_define_spec()
        confirmed["status"] = "confirmed"
        result = self.run_cli("validate", payload=confirmed)
        self.assertEqual(5, result.returncode)
        codes = [item["code"] for item in self.parsed(result)["errors"]]
        self.assertIn("CONFIRMED_REQUIRES_STATE", codes)
        self.assertIn("CONFIRMED_WITH_UNRESOLVED_UNKNOWNS", codes)

    def test_high_risk_verdict_boundary_scans_every_model_semantic_field_and_action_class(self) -> None:
        hidden_verdict = valid_high_risk_spec()
        hidden_verdict["desired_outcome"] = {
            "status": "hypothesis",
            "value": "你应该辞职。",
            "sources": [
                evidence("request", hidden_verdict["original_request"], "辞职")
            ],
        }
        synonym_verdict = valid_high_risk_spec()
        synonym_verdict["rewritten_problem"] = "你应该离开这家公司。"

        for label, spec in (
            ("hidden-model-field", hidden_verdict),
            ("career-exit-action-class", synonym_verdict),
        ):
            with self.subTest(label=label):
                result = self.run_cli("validate", payload=spec)
                self.assertEqual(5, result.returncode, result.stdout + result.stderr)
                codes = [item["code"] for item in self.parsed(result)["errors"]]
                self.assertIn("HIGH_RISK_VERDICT_FORBIDDEN", codes)

    def test_round_budget_becomes_a_terminal_state_and_blocks_more_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            self.start(state_path, valid_define_spec(), max_rounds=2)
            self.answer_define_round(state_path)
            continuing = valid_define_spec()
            result = self.run_cli(
                "advance",
                "--state",
                str(state_path),
                payload={"advance_id": "advance-round-2", "expected_revision": 4, "spec": continuing},
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            round_two = self.parsed(result)
            self.assertEqual(2, round_two["round"])
            self.assertEqual("awaiting_answers", round_two["phase"])
            self.answer_define_round(state_path, start_revision=5, prefix="b")

            exhausted = self.run_cli(
                "advance",
                "--state",
                str(state_path),
                payload={"advance_id": "advance-round-3", "expected_revision": 8, "spec": continuing},
            )
            self.assertEqual(0, exhausted.returncode, exhausted.stdout + exhausted.stderr)
            stopped = self.parsed(exhausted)
            self.assertEqual("budget_exhausted", stopped["phase"])
            self.assertEqual("max_rounds_reached", stopped["stop_reason"])

            blocked = self.run_cli(
                "resume",
                "--state",
                str(state_path),
                payload={
                    "answer_id": "too-late",
                    "question_id": "q1",
                    "answer": "不应再接受",
                    "expected_revision": stopped["revision"],
                },
            )
            self.assertEqual(5, blocked.returncode)
            self.assertEqual("LOOP_TERMINAL", self.parsed(blocked)["error"]["code"])

    def test_status_is_read_only_and_reports_machine_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            self.start(state_path, valid_define_spec())
            before = state_path.read_bytes()
            result = self.run_cli("status", "--state", str(state_path))
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            status = self.parsed(result)
            self.assertEqual("awaiting_answers", status["phase"])
            self.assertEqual(["resume"], status["allowed_actions"])
            self.assertRegex(status["state_digest"], r"^[a-f0-9]{64}$")
            self.assertEqual(before, state_path.read_bytes())

    def test_answer_can_be_amended_without_erasing_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            self.start(state_path, valid_define_spec())
            self.answer(
                state_path,
                answer_id="a1",
                question_id="q1",
                answer="减少访谈记录返工。",
                expected_revision=1,
            )
            result = self.run_cli(
                "amend",
                "--state",
                str(state_path),
                payload={
                    "amendment_id": "m1",
                    "answer_id": "a1",
                    "answer": "改为减少访谈记录遗漏。",
                    "expected_revision": 2,
                },
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            corrected = self.parsed(result)
            self.assertEqual("awaiting_answers", corrected["phase"])
            self.assertEqual("superseded", corrected["answers"][0]["status"])
            sources = {item["source_id"]: item for item in corrected["evidence_log"]}
            self.assertEqual("superseded", sources["answer:a1"]["status"])
            self.assertEqual("active", sources["amendment:m1"]["status"])

    def test_high_risk_tradeoff_can_only_be_resolved_by_a_user_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            spec = valid_high_risk_spec()
            self.start(state_path, spec)
            answers = (
                ("q1", "现金可以覆盖六个月，另有一个替代岗位。"),
                ("q2", "失眠是不能继续承受的健康损失。"),
                ("q3", HIGH_RISK_Q3),
            )
            for offset, (question_id, answer) in enumerate(answers):
                self.answer(
                    state_path,
                    answer_id=f"h{offset + 1}",
                    question_id=question_id,
                    answer=answer,
                    expected_revision=1 + offset,
                )
            resolved = copy.deepcopy(spec)
            resolved["status"] = "confirmed"
            resolved["desired_outcome"] = {
                "status": "stated",
                "value": HIGH_RISK_OUTCOME,
                "sources": [
                    evidence(
                        "answer:h3",
                        answers[2][1],
                        HIGH_RISK_OUTCOME,
                    )
                ],
            }
            resolved["decisive_unknowns"] = []
            resolved["questions"] = []
            resolved["success_evidence"] = [
                success_criterion(HIGH_RISK_CRITERION, "answer:h3", answers[2][1])
            ]
            advanced = self.run_cli(
                "advance",
                "--state",
                str(state_path),
                payload={"advance_id": "high-risk-ready", "expected_revision": 4, "spec": resolved},
            )
            self.assertEqual(0, advanced.returncode, advanced.stdout + advanced.stderr)
            self.assertEqual("awaiting_user_decision", self.parsed(advanced)["phase"])

            model = self.run_cli(
                "decide",
                "--state",
                str(state_path),
                payload={
                    "decision_id": "d-model",
                    "actor": "model",
                    "tradeoff_id": "t1",
                    "selection": "辞职",
                    "expected_revision": 5,
                },
            )
            self.assertEqual(5, model.returncode)
            self.assertEqual("USER_DECISION_REQUIRED", self.parsed(model)["error"]["code"])

            stale_problem_answer = self.run_cli(
                "decide",
                "--state",
                str(state_path),
                payload={
                    "decision_id": "d-stale-answer",
                    "actor": "user",
                    "tradeoff_id": "t1",
                    "selection": answers[2][1],
                    "source": evidence("answer:h3", answers[2][1]),
                    "expected_revision": 5,
                },
            )
            self.assertEqual(5, stale_problem_answer.returncode)
            self.assertEqual(
                "USER_DECISION_CURRENT_INPUT_REQUIRED",
                self.parsed(stale_problem_answer)["error"]["code"],
            )

            ambiguous_text = answers[0][1]
            ambiguous = self.run_cli(
                "decide",
                "--state",
                str(state_path),
                payload={
                    "decision_id": "d-ambiguous",
                    "actor": "user",
                    "tradeoff_id": "t1",
                    "selection": ambiguous_text,
                    "user_input": ambiguous_text,
                    "source": evidence("decision_input:d-ambiguous", ambiguous_text),
                    "expected_revision": 5,
                },
            )
            self.assertEqual(5, ambiguous.returncode)
            self.assertEqual(
                "USER_DECISION_NOT_EXPLICIT",
                self.parsed(ambiguous)["error"]["code"],
            )

            decision_text = "我选择留下并先谈条件。"
            user = self.run_cli(
                "decide",
                "--state",
                str(state_path),
                payload={
                    "decision_id": "d-user",
                    "actor": "user",
                    "tradeoff_id": "t1",
                    "selection": decision_text,
                    "user_input": decision_text,
                    "source": evidence("decision_input:d-user", decision_text),
                    "expected_revision": 5,
                },
            )
            self.assertEqual(0, user.returncode, user.stdout + user.stderr)
            decided = self.parsed(user)
            self.assertEqual("user_decision_recorded", decided["phase"])
            self.assertEqual("user", decided["user_decisions"][0]["actor"])
            self.assertEqual(decision_text, decided["user_decisions"][0]["user_input"])

    def test_all_high_risk_tradeoffs_require_one_fresh_decision_before_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            self.ready_high_risk_state(
                state_path,
                prefix="multi",
                tradeoff_count=2,
            )
            first_text = "我选择先谈条件并保留离开的路径。"
            first_payload = {
                "decision_id": "multi-d1",
                "actor": "user",
                "tradeoff_id": "t1",
                "selection": first_text,
                "user_input": first_text,
                "source": evidence("decision_input:multi-d1", first_text),
                "expected_revision": 5,
            }
            first = self.run_cli(
                "decide",
                "--state",
                str(state_path),
                payload=first_payload,
            )
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            partial = self.parsed(first)
            self.assertEqual("awaiting_user_decision", partial["phase"])
            self.assertEqual("value_tradeoff_requires_user", partial["stop_reason"])
            self.assertEqual(["t1"], [item["tradeoff_id"] for item in partial["user_decisions"]])
            self.assertEqual(6, partial["revision"])
            status = self.run_cli("status", "--state", str(state_path))
            self.assertEqual(0, status.returncode, status.stdout + status.stderr)
            self.assertIn("decide", self.parsed(status)["allowed_actions"])

            partial_bytes = state_path.read_bytes()
            replay = self.run_cli(
                "decide",
                "--state",
                str(state_path),
                payload=first_payload,
            )
            self.assertEqual(0, replay.returncode, replay.stdout + replay.stderr)
            self.assertEqual(partial_bytes, state_path.read_bytes())

            duplicate_text = "我决定仍先谈条件。"
            duplicate = self.run_cli(
                "decide",
                "--state",
                str(state_path),
                payload={
                    "decision_id": "multi-duplicate",
                    "actor": "user",
                    "tradeoff_id": "t1",
                    "selection": duplicate_text,
                    "user_input": duplicate_text,
                    "source": evidence("decision_input:multi-duplicate", duplicate_text),
                    "expected_revision": 6,
                },
            )
            self.assertEqual(5, duplicate.returncode, duplicate.stdout + duplicate.stderr)
            self.assertEqual("TRADEOFF_ALREADY_DECIDED", self.parsed(duplicate)["error"]["code"])
            self.assertEqual(partial_bytes, state_path.read_bytes())

            second_text = "我决定接受先比较两条路径再行动。"
            second = self.run_cli(
                "decide",
                "--state",
                str(state_path),
                payload={
                    "decision_id": "multi-d2",
                    "actor": "user",
                    "tradeoff_id": "t2",
                    "selection": second_text,
                    "user_input": second_text,
                    "source": evidence("decision_input:multi-d2", second_text),
                    "expected_revision": 6,
                },
            )
            self.assertEqual(0, second.returncode, second.stdout + second.stderr)
            terminal = self.parsed(second)
            self.assertEqual("user_decision_recorded", terminal["phase"])
            self.assertEqual("user_decision_recorded", terminal["stop_reason"])
            self.assertEqual({"t1", "t2"}, {item["tradeoff_id"] for item in terminal["user_decisions"]})
            self.assertEqual(7, terminal["revision"])

            terminal_bytes = state_path.read_bytes()
            terminal_replay = self.run_cli(
                "decide",
                "--state",
                str(state_path),
                payload=first_payload,
            )
            self.assertEqual(0, terminal_replay.returncode, terminal_replay.stdout + terminal_replay.stderr)
            self.assertEqual(terminal_bytes, state_path.read_bytes())

    def test_state_rejects_duplicate_tradeoff_decisions_even_with_unique_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            self.ready_high_risk_state(
                state_path,
                prefix="forged-multi",
                tradeoff_count=2,
            )
            first_text = "我选择先谈条件并保留离开的路径。"
            first_payload = {
                "decision_id": "forged-d1",
                "actor": "user",
                "tradeoff_id": "t1",
                "selection": first_text,
                "user_input": first_text,
                "source": evidence("decision_input:forged-d1", first_text),
                "expected_revision": 5,
            }
            first = self.run_cli(
                "decide",
                "--state",
                str(state_path),
                payload=first_payload,
            )
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)

            state = json.loads(state_path.read_text(encoding="utf-8"))
            second_text = "我决定继续先谈条件。"
            second_source = evidence("decision_input:forged-d2", second_text)
            second_payload = {
                "decision_id": "forged-d2",
                "actor": "user",
                "tradeoff_id": "t1",
                "selection": second_text,
                "user_input": second_text,
                "source": second_source,
                "expected_revision": 6,
            }
            state["evidence_log"].append(
                {
                    "kind": "decision_input",
                    "sha256": hashlib.sha256(second_text.encode()).hexdigest(),
                    "source_id": "decision_input:forged-d2",
                    "status": "active",
                    "superseded_by": None,
                    "text": second_text,
                }
            )
            state["user_decisions"].append(
                {
                    "actor": "user",
                    "decision_id": "forged-d2",
                    "selection": second_text,
                    "source": second_source,
                    "tradeoff_id": "t1",
                    "user_input": second_text,
                }
            )
            state["revision"] = 7
            state["events"].append(
                {
                    "event_id": "forged-d2",
                    "event_type": "decision",
                    "payload_digest": hashlib.sha256(
                        canonical_json(second_payload).encode()
                    ).hexdigest(),
                    "revision": 7,
                }
            )
            state["usage"]["user_decisions"] = 2
            state["phase"] = "user_decision_recorded"
            state["stop_reason"] = "user_decision_recorded"
            state_path.write_text(canonical_json(state) + "\n", encoding="utf-8")

            status = self.run_cli("status", "--state", str(state_path))
            self.assertEqual(4, status.returncode, status.stdout + status.stderr)
            self.assertEqual("STATE_INVALID", self.parsed(status)["error"]["code"])

    def test_one_unknown_without_questions_has_an_executable_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            spec = valid_define_spec()
            spec["domain"] = "general"
            spec["request_envelope"]["signals"]["domain"] = "general"
            spec["gate_receipt"] = gate_receipt(
                spec["request_envelope"],
                mode="define",
                rule="decisive_unknowns",
                priority_index=1,
                resources=["references/core.md"],
            )
            spec["decisive_unknowns"] = spec["decisive_unknowns"][:1]
            spec["questions"] = []

            started = self.start(state_path, spec)
            self.assertEqual("needs_reassessment", started["phase"])
            status = self.run_cli("status", "--state", str(state_path))
            self.assertEqual(0, status.returncode, status.stdout + status.stderr)
            self.assertEqual(["advance"], self.parsed(status)["allowed_actions"])

            advanced = self.run_cli(
                "advance",
                "--state",
                str(state_path),
                payload={"advance_id": "no-question-round", "expected_revision": 1, "spec": spec},
            )
            self.assertEqual(0, advanced.returncode, advanced.stdout + advanced.stderr)
            round_two = self.parsed(advanced)
            self.assertEqual("needs_reassessment", round_two["phase"])
            self.assertEqual(2, round_two["round"])

    def test_low_information_answers_cannot_fake_confirmation(self) -> None:
        for thin_outcome in ("好", "更好", "变优秀"):
            with self.subTest(thin_outcome=thin_outcome), tempfile.TemporaryDirectory() as temp_dir:
                state_path = Path(temp_dir) / "state.json"
                self.start(state_path, valid_define_spec())
                answers = (("q1", thin_outcome), ("q2", "不知道"), ("q3", "没有"))
                for offset, (question_id, answer) in enumerate(answers):
                    self.answer(
                        state_path,
                        answer_id=f"thin-{offset + 1}",
                        question_id=question_id,
                        answer=answer,
                        expected_revision=1 + offset,
                    )
                resolved = valid_define_spec()
                resolved["status"] = "confirmed"
                resolved["desired_outcome"] = {
                    "status": "stated",
                    "value": thin_outcome,
                    "sources": [evidence("answer:thin-1", thin_outcome)],
                }
                resolved["decisive_unknowns"] = []
                resolved["questions"] = []
                resolved["success_evidence"] = [thin_outcome]
                result = self.run_cli(
                    "advance",
                    "--state",
                    str(state_path),
                    payload={"advance_id": "thin-confirmation", "expected_revision": 4, "spec": resolved},
                )
                self.assertEqual(5, result.returncode)
                codes = [item["code"] for item in self.parsed(result)["errors"]]
                self.assertIn("CONFIRMED_OUTCOME_NOT_DETERMINATE", codes)
                self.assertIn("CONFIRMED_SUCCESS_EVIDENCE_NOT_DETERMINATE", codes)

    def test_confirmed_cannot_invent_acceptance_criteria_from_vague_user_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            self.start(state_path, valid_define_spec())
            answers = (
                ("q1", "我想变得更好。"),
                ("q2", "不知道。"),
                ("q3", "没有。"),
            )
            for offset, (question_id, answer) in enumerate(answers):
                self.answer(
                    state_path,
                    answer_id=f"vague-{offset + 1}",
                    question_id=question_id,
                    answer=answer,
                    expected_revision=1 + offset,
                )

            resolved = valid_define_spec()
            resolved["status"] = "confirmed"
            resolved["desired_outcome"] = {
                "status": "stated",
                "value": "我想变得更好",
                "sources": [evidence("answer:vague-1", answers[0][1], "我想变得更好")],
            }
            resolved["decisive_unknowns"] = []
            resolved["questions"] = []
            resolved["success_evidence"] = ["记录我是否变得更好。"]

            result = self.run_cli(
                "advance",
                "--state",
                str(state_path),
                payload={
                    "advance_id": "vague-false-confirmation",
                    "expected_revision": 4,
                    "spec": resolved,
                },
            )
            self.assertEqual(5, result.returncode, result.stdout + result.stderr)
            codes = [item["code"] for item in self.parsed(result)["errors"]]
            self.assertIn("CONFIRMED_SUCCESS_EVIDENCE_NOT_USER_SUPPORTED", codes)
            self.assertIn("CONFIRMED_SUCCESS_EVIDENCE_NOT_DETERMINATE", codes)

    def test_amending_a_cited_answer_keeps_state_readable_but_old_evidence_unusable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            self.start(state_path, valid_define_spec(), max_rounds=3)
            self.answer_define_round(state_path)
            continuing = valid_define_spec()
            answer = "减少访谈记录返工。"
            continuing["desired_outcome"] = {
                "status": "stated",
                "value": "减少访谈记录返工",
                "sources": [evidence("answer:a1", answer, "减少访谈记录返工")],
            }
            advanced = self.run_cli(
                "advance",
                "--state",
                str(state_path),
                payload={"advance_id": "round-two", "expected_revision": 4, "spec": continuing},
            )
            self.assertEqual(0, advanced.returncode, advanced.stdout + advanced.stderr)
            amended = self.run_cli(
                "amend",
                "--state",
                str(state_path),
                payload={
                    "amendment_id": "m-cited",
                    "answer_id": "a1",
                    "answer": "改为减少访谈记录遗漏。",
                    "expected_revision": 5,
                },
            )
            self.assertEqual(0, amended.returncode, amended.stdout + amended.stderr)
            status = self.run_cli("status", "--state", str(state_path))
            self.assertEqual(0, status.returncode, status.stdout + status.stderr)
            self.assertEqual("awaiting_answers", self.parsed(status)["phase"])

    def test_confirmed_requires_stated_outcome_and_success_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            self.start(state_path, valid_define_spec())
            self.answer_define_round(state_path)
            invalid = self.resolved_define_spec()
            invalid["desired_outcome"]["status"] = "hypothesis"
            invalid["success_evidence"] = []
            result = self.run_cli(
                "advance",
                "--state",
                str(state_path),
                payload={"advance_id": "false-confirmation", "expected_revision": 4, "spec": invalid},
            )
            self.assertEqual(5, result.returncode)
            codes = [item["code"] for item in self.parsed(result)["errors"]]
            self.assertIn("CONFIRMED_OUTCOME_NOT_STATED", codes)
            self.assertIn("CONFIRMED_SUCCESS_EVIDENCE_REQUIRED", codes)

            unrelated = self.resolved_define_spec()
            unrelated["desired_outcome"]["value"] = "成为世界首富"
            result = self.run_cli(
                "advance",
                "--state",
                str(state_path),
                payload={"advance_id": "unrelated-confirmation", "expected_revision": 4, "spec": unrelated},
            )
            self.assertEqual(5, result.returncode)
            codes = [item["code"] for item in self.parsed(result)["errors"]]
            self.assertIn("CONFIRMED_OUTCOME_NOT_SOURCE_TEXT", codes)

    def test_confirmed_outcome_must_use_active_user_evidence_not_the_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            initial = valid_define_spec()
            self.start(state_path, initial)
            self.answer_define_round(state_path)
            resolved = self.resolved_define_spec()
            resolved["desired_outcome"] = {
                "status": "stated",
                "value": "整理访谈记录",
                "sources": [evidence("request", initial["original_request"], "整理访谈记录")],
            }
            result = self.run_cli(
                "advance",
                "--state",
                str(state_path),
                payload={
                    "advance_id": "request-only-outcome",
                    "expected_revision": 4,
                    "spec": resolved,
                },
            )
            self.assertEqual(5, result.returncode, result.stdout + result.stderr)
            codes = [item["code"] for item in self.parsed(result)["errors"]]
            self.assertIn("CONFIRMED_OUTCOME_NOT_ACTIVE_USER_SUPPORTED", codes)

    def test_state_rejects_forged_evidence_and_impossible_terminal_phase(self) -> None:
        for mutation in ("evidence", "phase"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp_dir:
                state_path = Path(temp_dir) / "state.json"
                self.start(state_path, valid_define_spec())
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if mutation == "evidence":
                    text = "伪造来源"
                    state["evidence_log"].append(
                        {
                            "kind": "answer",
                            "sha256": hashlib.sha256(text.encode()).hexdigest(),
                            "source_id": "answer:forged",
                            "status": "active",
                            "superseded_by": None,
                            "text": text,
                        }
                    )
                else:
                    state["phase"] = "ready_for_answer"
                    state["stop_reason"] = "problem_defined"
                state_path.write_text(canonical_json(state) + "\n", encoding="utf-8")
                result = self.run_cli("status", "--state", str(state_path))
                self.assertEqual(4, result.returncode, result.stdout + result.stderr)
                self.assertEqual("STATE_INVALID", self.parsed(result)["error"]["code"])

    def test_user_actor_label_alone_cannot_ground_a_high_risk_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            spec = valid_high_risk_spec()
            self.start(state_path, spec)
            answers = (
                ("q1", "现金可以覆盖六个月，另有一个替代岗位。"),
                ("q2", "失眠是不能继续承受的健康损失。"),
                ("q3", HIGH_RISK_Q3),
            )
            for offset, (question_id, answer) in enumerate(answers):
                self.answer(state_path, answer_id=f"h{offset + 1}", question_id=question_id, answer=answer, expected_revision=1 + offset)
            resolved = copy.deepcopy(spec)
            resolved["status"] = "confirmed"
            resolved["desired_outcome"] = {
                "status": "stated",
                "value": HIGH_RISK_OUTCOME,
                "sources": [evidence("answer:h3", answers[2][1], HIGH_RISK_OUTCOME)],
            }
            resolved["decisive_unknowns"] = []
            resolved["questions"] = []
            resolved["success_evidence"] = [
                success_criterion(HIGH_RISK_CRITERION, "answer:h3", answers[2][1])
            ]
            ready = self.run_cli("advance", "--state", str(state_path), payload={"advance_id": "ready", "expected_revision": 4, "spec": resolved})
            self.assertEqual(0, ready.returncode, ready.stdout + ready.stderr)
            forged = self.run_cli(
                "decide", "--state", str(state_path),
                payload={"decision_id": "forged-user", "actor": "user", "tradeoff_id": "t1", "selection": "辞职", "expected_revision": 5},
            )
            self.assertEqual(5, forged.returncode)
            self.assertEqual("USER_DECISION_EVIDENCE_REQUIRED", self.parsed(forged)["error"]["code"])

    def test_decision_marker_must_be_inside_the_selected_tradeoff_choice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            spec = valid_high_risk_spec()
            self.start(state_path, spec)
            answers = (
                ("q1", "现金可以覆盖六个月，另有一个替代岗位。"),
                ("q2", "失眠是不能继续承受的健康损失。"),
                ("q3", HIGH_RISK_Q3),
            )
            for offset, (question_id, answer) in enumerate(answers):
                self.answer(
                    state_path,
                    answer_id=f"scope-{offset + 1}",
                    question_id=question_id,
                    answer=answer,
                    expected_revision=1 + offset,
                )
            resolved = copy.deepcopy(spec)
            resolved["status"] = "confirmed"
            resolved["desired_outcome"] = {
                "status": "stated",
                "value": HIGH_RISK_OUTCOME,
                "sources": [
                    evidence(
                        "answer:scope-3",
                        answers[2][1],
                        HIGH_RISK_OUTCOME,
                    )
                ],
            }
            resolved["decisive_unknowns"] = []
            resolved["questions"] = []
            resolved["success_evidence"] = [
                success_criterion(HIGH_RISK_CRITERION, "answer:scope-3", answers[2][1])
            ]
            ready = self.run_cli(
                "advance",
                "--state",
                str(state_path),
                payload={"advance_id": "scope-ready", "expected_revision": 4, "spec": resolved},
            )
            self.assertEqual(0, ready.returncode, ready.stdout + ready.stderr)
            self.assertEqual("awaiting_user_decision", self.parsed(ready)["phase"])

            user_input = "我决定明天吃饭。现金覆盖六个月。"
            background_fact = "现金覆盖六个月"
            result = self.run_cli(
                "decide",
                "--state",
                str(state_path),
                payload={
                    "decision_id": "scope-bypass",
                    "actor": "user",
                    "tradeoff_id": "t1",
                    "selection": background_fact,
                    "user_input": user_input,
                    "source": evidence("decision_input:scope-bypass", user_input, background_fact),
                    "expected_revision": 5,
                },
            )
            self.assertEqual(5, result.returncode, result.stdout + result.stderr)
            self.assertEqual("USER_DECISION_NOT_EXPLICIT", self.parsed(result)["error"]["code"])

    def test_decision_marker_without_positive_commitment_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            spec = valid_high_risk_spec()
            self.start(state_path, spec)
            answers = (
                ("q1", "现金可以覆盖六个月，另有一个替代岗位。"),
                ("q2", "失眠是不能继续承受的健康损失。"),
                ("q3", HIGH_RISK_Q3),
            )
            for offset, (question_id, answer) in enumerate(answers):
                self.answer(
                    state_path,
                    answer_id=f"commit-{offset + 1}",
                    question_id=question_id,
                    answer=answer,
                    expected_revision=1 + offset,
                )
            resolved = copy.deepcopy(spec)
            resolved["status"] = "confirmed"
            resolved["desired_outcome"] = {
                "status": "stated",
                "value": HIGH_RISK_OUTCOME,
                "sources": [
                    evidence(
                        "answer:commit-3",
                        answers[2][1],
                        HIGH_RISK_OUTCOME,
                    )
                ],
            }
            resolved["decisive_unknowns"] = []
            resolved["questions"] = []
            resolved["success_evidence"] = [
                success_criterion(HIGH_RISK_CRITERION, "answer:commit-3", answers[2][1])
            ]
            ready = self.run_cli(
                "advance",
                "--state",
                str(state_path),
                payload={"advance_id": "commit-ready", "expected_revision": 4, "spec": resolved},
            )
            self.assertEqual(0, ready.returncode, ready.stdout + ready.stderr)
            self.assertEqual("awaiting_user_decision", self.parsed(ready)["phase"])

            non_commitments = (
                ("我决定不了。", "USER_DECISION_NOT_COMMITTED"),
                ("我没有决定。", "USER_DECISION_NOT_COMMITTED"),
                ("我还没决定。", "USER_DECISION_NOT_COMMITTED"),
                ("我无法决定。", "USER_DECISION_NOT_COMMITTED"),
                ("我决定辞职吗？", "USER_DECISION_NOT_COMMITTED"),
                ("难道我决定辞职？", "USER_DECISION_NOT_COMMITTED"),
                ("我会再想想。", "USER_DECISION_NOT_EXPLICIT"),
            )
            for offset, (no_commitment, expected_code) in enumerate(non_commitments, start=1):
                with self.subTest(no_commitment=no_commitment):
                    decision_id = f"not-committed-{offset}"
                    result = self.run_cli(
                        "decide",
                        "--state",
                        str(state_path),
                        payload={
                            "decision_id": decision_id,
                            "actor": "user",
                            "tradeoff_id": "t1",
                            "selection": no_commitment,
                            "user_input": no_commitment,
                            "source": evidence(f"decision_input:{decision_id}", no_commitment),
                            "expected_revision": 5,
                        },
                    )
                    self.assertEqual(5, result.returncode, result.stdout + result.stderr)
                    self.assertEqual(
                        expected_code,
                        self.parsed(result)["error"]["code"],
                    )

    def test_answer_replay_must_match_the_original_expected_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            self.start(state_path, valid_define_spec())
            self.answer(state_path, answer_id="a1", question_id="q1", answer="减少返工。", expected_revision=1)
            replay = self.run_cli(
                "resume", "--state", str(state_path),
                payload={"answer_id": "a1", "question_id": "q1", "answer": "减少返工。", "expected_revision": 999},
            )
            self.assertEqual(5, replay.returncode)
            self.assertEqual("ANSWER_ID_CONFLICT", self.parsed(replay)["error"]["code"])


if __name__ == "__main__":
    unittest.main()
