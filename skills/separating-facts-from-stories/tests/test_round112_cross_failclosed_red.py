from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
CASEFILE_CLI = SKILL_DIR / "scripts" / "casefile.py"
WORKFLOW_CLI = SKILL_DIR / "scripts" / "workflow.py"


def _run(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *(str(item) for item in args)],
        text=True,
        capture_output=True,
        check=False,
    )


def _json_output(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    raw = result.stdout.strip() or result.stderr.strip()
    if not raw:
        raise AssertionError(f"command returned no JSON: {result.args!r}")
    return json.loads(raw)


def _init_casefile(
    root: Path,
    text: str,
    case_id: str,
) -> tuple[dict[str, Any], Path]:
    input_path = root / f"{case_id}-input.txt"
    artifact_path = root / f"{case_id}.json"
    input_path.write_text(text, encoding="utf-8")
    result = _run(
        CASEFILE_CLI,
        "init",
        "--input",
        input_path,
        "--output",
        artifact_path,
        "--case-id",
        case_id,
        "--mode",
        "auto",
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return json.loads(artifact_path.read_text(encoding="utf-8")), artifact_path


def _write_and_validate(
    artifact: dict[str, Any], artifact_path: Path
) -> dict[str, Any]:
    artifact_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return _json_output(_run(CASEFILE_CLI, "validate", artifact_path))


def _add_unknown_action_and_decision(artifact: dict[str, Any]) -> None:
    artifact["unknowns"] = [
        {
            "id": "U1",
            "unknown_type": "event_cause_or_context",
            "text": "当前事件的具体原因或上下文是什么",
            "status": "open",
            "resolved_by_evidence_refs": [],
        }
    ]
    artifact["actions"] = [
        {
            "id": "A1",
            "action_type": "record_pattern",
            "text": "记录后续发生的具体行为、时间和结果",
            "timing": "next",
            "risk": "low",
            "reversible": True,
            "motive_independent": True,
            "produces_new_evidence": True,
        }
    ]
    artifact["user_decisions"] = ["evidence_threshold"]


def _complete_with_first_fact_only(artifact: dict[str, Any]) -> None:
    span = artifact["source_spans"][0]
    artifact["claims"] = [
        {
            "id": "C1",
            "kind": "observable_fact",
            "observation_type": "participation_or_schedule_event",
            "text": span["text"],
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "user_direct_observation",
            "exact_quote": span["text"],
            "epistemic_status": "reported",
            "diagnostic_boundary": False,
        }
    ]
    artifact["evidence"] = [
        {
            "id": "E1",
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "user_direct_observation",
            "exact_quote": span["text"],
            "can_establish": ["C1"],
            "cannot_establish": [],
            "limitations": ["single_party_report"],
        }
    ]
    artifact["evidence_links"] = [
        {
            "proposition_id": "C1",
            "evidence_ref": "E1",
            "relation": "supports",
            "strength": "direct",
            "reason": "anchor_matches_report",
        }
    ]
    _add_unknown_action_and_decision(artifact)


def _complete_with_direct_position(
    artifact: dict[str, Any], quoted_span: dict[str, Any]
) -> None:
    artifact["claims"] = [
        {
            "id": "C1",
            "kind": "stated_position",
            "text": quoted_span["text"],
            "input_id": quoted_span["input_id"],
            "source_span_id": quoted_span["id"],
            "source_ref": quoted_span["source_ref"],
            "source_type": "direct_quote",
            "exact_quote": quoted_span["text"],
            "epistemic_status": "directly_stated",
            "diagnostic_boundary": False,
        }
    ]
    artifact["evidence"] = [
        {
            "id": "E1",
            "input_id": quoted_span["input_id"],
            "source_span_id": quoted_span["id"],
            "source_ref": quoted_span["source_ref"],
            "source_type": "direct_quote",
            "exact_quote": quoted_span["text"],
            "can_establish": ["C1"],
            "cannot_establish": [],
            "limitations": ["single_party_report"],
        }
    ]
    artifact["evidence_links"] = [
        {
            "proposition_id": "C1",
            "evidence_ref": "E1",
            "relation": "supports",
            "strength": "direct",
            "reason": "direct_current_statement_only",
        }
    ]
    _add_unknown_action_and_decision(artifact)


def _complete_with_prediction(
    artifact: dict[str, Any], prediction_span: dict[str, Any]
) -> None:
    artifact["claims"] = [
        {
            "id": "C1",
            "kind": "prediction",
            "text": prediction_span["text"],
            "input_id": prediction_span["input_id"],
            "source_span_id": prediction_span["id"],
            "source_ref": prediction_span["source_ref"],
            "source_type": "user_report",
            "exact_quote": prediction_span["text"],
            "epistemic_status": "unverified",
            "diagnostic_boundary": False,
        }
    ]
    artifact["evidence"] = [
        {
            "id": "E1",
            "input_id": prediction_span["input_id"],
            "source_span_id": prediction_span["id"],
            "source_ref": prediction_span["source_ref"],
            "source_type": "user_report",
            "exact_quote": prediction_span["text"],
            "can_establish": [],
            "cannot_establish": ["C1"],
            "limitations": ["single_party_report"],
        }
    ]
    artifact["evidence_links"] = [
        {
            "proposition_id": "C1",
            "evidence_ref": "E1",
            "relation": "does_not_establish",
            "strength": "none",
            "reason": "source_scope_limit",
        }
    ]
    _add_unknown_action_and_decision(artifact)


class Round112CrossFailClosedRedTests(unittest.TestCase):
    """Public-entry RED cases for four cross-cutting fail-closed gaps."""

    def test_relayed_position_cannot_validate_as_direct_quote(self) -> None:
        cases = (
            "中间人代为带话，老板表示：\u201c我会留下。\u201d",
            "从秘书口中转了一道，老板说：\u201c我会留下。\u201d",
        )
        with tempfile.TemporaryDirectory(prefix="round112-source-") as raw:
            root = Path(raw)
            for index, text in enumerate(cases, start=1):
                with self.subTest(text=text):
                    artifact, path = _init_casefile(
                        root, text, f"round112-source-{index}"
                    )
                    quoted = next(
                        item
                        for item in artifact["source_spans"]
                        if item["quoted"] is True
                    )
                    _complete_with_direct_position(artifact, quoted)
                    report = _write_and_validate(artifact, path)
                    codes = {item["code"] for item in report["errors"]}
                    self.assertFalse(report["valid"])
                    self.assertTrue(
                        codes
                        & {
                            "SOURCE_TYPE_MISMATCH",
                            "DIRECT_QUOTE_NOT_ASSERTED",
                            "CLAIM_KIND_NOT_DERIVED",
                        }
                    )

    def test_unrecognized_observation_cannot_be_silently_omitted(self) -> None:
        cases = (
            "老板取消了会议。随后我的蓝色工牌被剪成两半。",
            "老板取消了会议。接着会议室门口多了一把铜挂锁。",
        )
        with tempfile.TemporaryDirectory(prefix="round112-observation-") as raw:
            root = Path(raw)
            for index, text in enumerate(cases, start=1):
                with self.subTest(text=text):
                    artifact, path = _init_casefile(
                        root, text, f"round112-observation-{index}"
                    )
                    omitted_span = artifact["source_spans"][1]
                    _complete_with_first_fact_only(artifact)
                    report = _write_and_validate(artifact, path)
                    codes = {item["code"] for item in report["errors"]}
                    candidate_visible = any(
                        item["source_span_id"] == omitted_span["id"]
                        for item in artifact[
                            "unclassified_observation_candidates"
                        ]
                    )
                    omission_rejected = not report["valid"] and bool(
                        codes
                        & {
                            "OBSERVABLE_FACT_CLAIM_MISSING",
                            "OBSERVATION_CANDIDATE_SET_MISMATCH",
                            "SOURCE_SPAN_UNCONSUMED",
                        }
                    )
                    self.assertTrue(candidate_visible or omission_rejected)

    def test_unrecognized_story_cannot_be_silently_omitted(self) -> None:
        cases = (
            "老板取消了会议。我由此认定他是在给我下马威。",
            "老板取消了会议。在我看来这是一场敲山震虎。",
        )
        with tempfile.TemporaryDirectory(prefix="round112-story-") as raw:
            root = Path(raw)
            for index, text in enumerate(cases, start=1):
                with self.subTest(text=text):
                    artifact, path = _init_casefile(
                        root, text, f"round112-story-{index}"
                    )
                    _complete_with_first_fact_only(artifact)
                    report = _write_and_validate(artifact, path)
                    codes = {item["code"] for item in report["errors"]}
                    self.assertFalse(report["valid"])
                    self.assertTrue(
                        codes
                        & {
                            "USER_STORY_CLAIM_MISSING",
                            "SOURCE_SPAN_UNCONSUMED",
                        }
                    )

    def test_translation_passthrough_cannot_complete_only_first_task(
        self,
    ) -> None:
        cases = (
            (
                "翻译成英文：他没回消息。另问：他这样做是不是故意惩罚我？",
                "He did not reply.",
            ),
            (
                "翻译成英文：她取消了约会。补问：这是不是在故意惩罚我？",
                "She canceled the date.",
            ),
        )
        with tempfile.TemporaryDirectory(prefix="round112-passthrough-") as raw:
            root = Path(raw)
            for index, (text, response_text) in enumerate(cases, start=1):
                with self.subTest(text=text):
                    input_path = root / f"input-{index}.txt"
                    response_path = root / f"response-{index}.txt"
                    workspace = root / f"workspace-{index}"
                    input_path.write_text(text, encoding="utf-8")
                    response_path.write_text(response_text, encoding="utf-8")
                    start = _run(
                        WORKFLOW_CLI,
                        "start",
                        "--input",
                        input_path,
                        "--workspace",
                        workspace,
                        "--case-id",
                        f"round112-passthrough-{index}",
                        "--mode",
                        "auto",
                    )
                    self.assertEqual(0, start.returncode, start.stderr)
                    started = _json_output(start)
                    completed: dict[str, Any] | None = None
                    completion = None
                    if started["mode"] == "passthrough":
                        completion = _run(
                            WORKFLOW_CLI,
                            "complete-passthrough",
                            "--workspace",
                            workspace,
                            "--response",
                            response_path,
                        )
                        if completion.returncode == 0:
                            completed = _json_output(completion)
                    swallowed = (
                        started["mode"] == "passthrough"
                        and completion is not None
                        and completion.returncode == 0
                        and completed is not None
                        and completed["phase"] == "completed"
                    )
                    self.assertFalse(swallowed)
                    self.assertEqual("standard", started["mode"])

    def test_rhetorical_denial_cannot_validate_as_prediction(self) -> None:
        cases = (
            "谁能说这就证明老板会开掉我？",
            "凭什么说这就证明公司会辞退我？",
        )
        with tempfile.TemporaryDirectory(prefix="round112-rhetorical-") as raw:
            root = Path(raw)
            for index, text in enumerate(cases, start=1):
                with self.subTest(text=text):
                    artifact, path = _init_casefile(
                        root, text, f"round112-rhetorical-{index}"
                    )
                    _complete_with_prediction(
                        artifact, artifact["source_spans"][0]
                    )
                    report = _write_and_validate(artifact, path)
                    codes = {item["code"] for item in report["errors"]}
                    self.assertFalse(report["valid"])
                    self.assertTrue(
                        codes
                        & {
                            "CLAIM_KIND_NOT_DERIVED",
                            "USER_STORY_SCOPE_INVALID",
                            "SOURCE_SPAN_UNCONSUMED",
                        }
                    )

    def test_concessive_antecedent_cannot_validate_as_prediction(self) -> None:
        cases = (
            "即便老板会开掉我，也不能据此说他恨我。",
            "纵然公司会辞退我，也不能由此断定领导讨厌我。",
        )
        with tempfile.TemporaryDirectory(prefix="round112-concessive-") as raw:
            root = Path(raw)
            for index, text in enumerate(cases, start=1):
                with self.subTest(text=text):
                    artifact, path = _init_casefile(
                        root, text, f"round112-concessive-{index}"
                    )
                    _complete_with_prediction(
                        artifact, artifact["source_spans"][0]
                    )
                    report = _write_and_validate(artifact, path)
                    codes = {item["code"] for item in report["errors"]}
                    self.assertFalse(report["valid"])
                    self.assertTrue(
                        codes
                        & {
                            "CLAIM_KIND_NOT_DERIVED",
                            "USER_STORY_SCOPE_INVALID",
                            "SOURCE_SPAN_UNCONSUMED",
                        }
                    )


if __name__ == "__main__":
    unittest.main()
