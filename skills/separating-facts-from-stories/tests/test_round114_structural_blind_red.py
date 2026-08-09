import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
CASEFILE_SCRIPT = SKILL_DIR / "scripts" / "casefile.py"
WORKFLOW_SCRIPT = SKILL_DIR / "scripts" / "workflow.py"


def load_casefile():
    spec = importlib.util.spec_from_file_location(
        "round114_structural_blind_casefile", CASEFILE_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Round114StructuralBlindRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.casefile = load_casefile()

    def case_with_only_first_observation(self, text: str) -> dict:
        """Build an otherwise valid case that consumes only the first event."""
        case = self.casefile.make_draft(text, "round114-structural", "standard")
        first_span = case["source_spans"][0]
        quote = first_span["text"]
        case["claims"] = [
            {
                "id": "C1",
                "kind": "observable_fact",
                "observation_type": "participation_or_schedule_event",
                "text": quote,
                "input_id": "I1",
                "source_span_id": first_span["id"],
                "source_ref": first_span["source_ref"],
                "source_type": "user_direct_observation",
                "exact_quote": quote,
                "epistemic_status": "reported",
                "diagnostic_boundary": False,
            }
        ]
        case["evidence"] = [
            {
                "id": "E1",
                "input_id": "I1",
                "source_span_id": first_span["id"],
                "source_ref": first_span["source_ref"],
                "source_type": "user_direct_observation",
                "exact_quote": quote,
                "can_establish": ["C1"],
                "cannot_establish": [],
                "limitations": ["single_party_report"],
            }
        ]
        case["evidence_links"] = [
            {
                "proposition_id": "C1",
                "evidence_ref": "E1",
                "relation": "supports",
                "strength": "direct",
                "reason": "anchor_matches_report",
            }
        ]
        case["unknowns"] = [
            {
                "id": "U1",
                "unknown_type": "event_cause_or_context",
                "text": "当前事件的具体原因或上下文是什么",
                "status": "open",
                "resolved_by_evidence_refs": [],
            }
        ]
        case["actions"] = [
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
        case["user_decisions"] = ["evidence_threshold"]
        return case

    def run_workflow(self, *args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(WORKFLOW_SCRIPT), *map(str, args)],
            cwd=SKILL_DIR,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_interrogatives_are_not_required_as_asserted_user_stories(self):
        cases = {
            "identity_question": "老板取消了会议。他是不是回避型？",
            "future_question": "她取消了约会。她会不会永远不回来？",
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                artifact = self.case_with_only_first_observation(text)
                codes = {
                    item["code"]
                    for item in self.casefile.validate_casefile(artifact)
                }
                self.assertNotIn(
                    "USER_STORY_CLAIM_MISSING",
                    codes,
                    "A question asks the runtime to keep an outcome unknown; "
                    "it is not the user's asserted identity or future story.",
                )

    def test_explicit_interpretation_frames_cannot_be_silently_omitted(self):
        cases = {
            "decode_frame": (
                "老板取消了项目会。"
                "我将这解读为自己被排除在决策之外。"
            ),
            "signal_frame": (
                "她取消了约会。"
                "我把这个信号看成关系已经降级。"
            ),
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                artifact = self.case_with_only_first_observation(text)
                codes = {
                    item["code"]
                    for item in self.casefile.validate_casefile(artifact)
                }
                self.assertIn(
                    "USER_STORY_CLAIM_MISSING",
                    codes,
                    "The user explicitly owns an interpretation, so a valid "
                    "artifact must not omit it merely because its framing verb "
                    "is absent from the current marker list.",
                )

    def test_unsupported_observable_events_remain_pending_candidates(self):
        cases = {
            "lock_event": (
                "老板取消了会议。老板锁上了办公室的门。",
                "老板锁上了办公室的门。",
            ),
            "take_event": (
                "经理取消了项目会。同事取走了会议室钥匙。",
                "同事取走了会议室钥匙。",
            ),
        }
        for label, (text, expected_candidate) in cases.items():
            with self.subTest(label=label):
                artifact = self.case_with_only_first_observation(text)
                candidate_quotes = {
                    item["exact_quote"]
                    for item in artifact["unclassified_observation_candidates"]
                }
                validation_codes = [
                    item["code"]
                    for item in self.casefile.validate_casefile(artifact)
                ]
                self.assertIn(
                    expected_candidate,
                    candidate_quotes,
                    "An ordinary asserted event outside the finite fact grammar "
                    "must remain visible as pending_confirmation instead of "
                    f"being silently accepted as omitted; validator={validation_codes}",
                )

    def test_analysis_requests_with_source_and_timeline_do_not_passthrough(self):
        cases = {
            "attitude_analysis": (
                "来源：聊天记录。她连续两次取消约会。"
                "请按时间线帮我看懂她对我的态度。"
            ),
            "inner_state_analysis": (
                "来源：同事转述。老板取消了项目会。"
                "按时间线帮我琢磨他心里怎么想。"
            ),
        }
        for label, text in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                input_path = root / "input.txt"
                workspace = root / "workspace"
                input_path.write_text(text, encoding="utf-8")
                completed = self.run_workflow(
                    "start",
                    "--input",
                    input_path,
                    "--workspace",
                    workspace,
                    "--case-id",
                    f"round114-{label}",
                    "--mode",
                    "auto",
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
                result = json.loads(completed.stdout)
                self.assertEqual(
                    "standard",
                    result["mode"],
                    "A request to infer attitude or inner state is analysis, not "
                    "a sourced-timeline transform, even when both lexical labels "
                    "are present.",
                )
                self.assertEqual("awaiting_authoring", result["phase"])

    def test_passthrough_rejects_added_conclusions_for_a_real_timeline_task(self):
        request = (
            "来源：[T1] 她取消了约会；[T2] 她把约会改期到周五。"
            "请按时间线整理。"
        )
        responses = {
            "priority_conclusion": (
                "T1：她取消约会；T2：她改期到周五；"
                "因此她一直把你放在次要位置。"
            ),
            "relationship_conclusion": (
                "T1：她取消约会；T2：她改期到周五；"
                "这段关系已经明显降级。"
            ),
        }
        for label, response_text in responses.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                input_path = root / "input.txt"
                response_path = root / "response.md"
                workspace = root / "workspace"
                input_path.write_text(request, encoding="utf-8")
                response_path.write_text(response_text, encoding="utf-8")
                started = self.run_workflow(
                    "start",
                    "--input",
                    input_path,
                    "--workspace",
                    workspace,
                    "--case-id",
                    f"round114-response-{label}",
                    "--mode",
                    "auto",
                )
                self.assertEqual(0, started.returncode, started.stderr)
                self.assertEqual(
                    "passthrough_required", json.loads(started.stdout)["phase"]
                )
                completed = self.run_workflow(
                    "complete-passthrough",
                    "--workspace",
                    workspace,
                    "--response",
                    response_path,
                )
                self.assertNotEqual(
                    0,
                    completed.returncode,
                    "A timeline-only response may preserve and reorder source "
                    "events, but it must not add a new relational conclusion.",
                )
                self.assertIn("PASSTHROUGH_SCOPE_VIOLATION", completed.stderr)


if __name__ == "__main__":
    unittest.main()
