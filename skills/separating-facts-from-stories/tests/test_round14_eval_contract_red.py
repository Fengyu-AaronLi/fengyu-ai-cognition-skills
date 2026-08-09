import importlib.util
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
RUNNER = SKILL_DIR / "scripts" / "run_evals.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("round14_eval_runner", RUNNER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FrozenEvalContractSatisfiabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load_runner()
        cls.casefile = cls.runner.CASEFILE

    def standard_draft(
        self,
        case_id,
        *,
        unknown_type,
        user_decision,
        action_type="neutral_check",
    ):
        frozen = self.runner.EXPECTED_CASES[case_id]
        artifact = self.casefile.make_draft(frozen["input"], case_id, "standard")
        artifact["unknowns"] = [
            {
                "id": "U1",
                "unknown_type": unknown_type,
                "text": self.casefile.UNKNOWN_CATALOG[unknown_type],
                "status": "open",
                "resolved_by_evidence_refs": [],
            }
        ]
        action = {
            key: value
            for key, value in self.casefile.ACTION_CATALOG[action_type].items()
            if key != "modes"
        }
        artifact["actions"] = [
            {"id": "A1", "action_type": action_type, **action}
        ]
        artifact["user_decisions"] = [user_decision]
        return artifact

    def span(self, artifact, source_ref, exact_text):
        matches = [
            item
            for item in artifact["source_spans"]
            if item["source_ref"] == source_ref and item["text"] == exact_text
        ]
        self.assertEqual(
            1,
            len(matches),
            f"expected exactly one generated span for {source_ref}: {exact_text}",
        )
        return matches[0]

    @staticmethod
    def claim(
        claim_id,
        span,
        *,
        kind,
        source_type,
        epistemic_status,
        observation_type=None,
        diagnostic_boundary=False,
    ):
        item = {
            "id": claim_id,
            "kind": kind,
            "text": span["text"],
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": source_type,
            "exact_quote": span["text"],
            "epistemic_status": epistemic_status,
            "diagnostic_boundary": diagnostic_boundary,
        }
        if observation_type is not None:
            item["observation_type"] = observation_type
        return item

    @staticmethod
    def attach_evidence(
        artifact,
        claim,
        evidence_id,
        span,
        *,
        source_type,
        relation,
    ):
        limitations = (
            ["secondhand"]
            if source_type == "secondhand"
            else ["artifact_not_verified"]
            if source_type == "unverified_artifact"
            else ["single_party_report"]
        )
        artifact["evidence"].append(
            {
                "id": evidence_id,
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": source_type,
                "exact_quote": span["text"],
                "can_establish": [claim["id"]] if relation == "supports" else [],
                "cannot_establish": [] if relation == "supports" else [claim["id"]],
                "limitations": limitations,
            }
        )
        direct_support = relation == "supports" and claim["kind"] in {
            "observable_fact",
            "explicit_feeling",
            "stated_position",
        }
        strength = (
            "none"
            if relation == "does_not_establish"
            else "direct"
            if direct_support
            else "weak"
        )
        reason = (
            "source_scope_limit"
            if relation == "does_not_establish"
            else "counter_signal_with_limited_scope"
            if relation == "conflicts"
            else "anchor_matches_report"
            if direct_support
            else "behavior_is_compatible_but_not_diagnostic"
        )
        artifact["evidence_links"].append(
            {
                "proposition_id": claim["id"],
                "evidence_ref": evidence_id,
                "relation": relation,
                "strength": strength,
                "reason": reason,
            }
        )

    def assert_joint_contract(self, case_id, artifact):
        self.assertEqual(
            [],
            self.runner.semantic_errors(case_id, artifact),
            "test witness must first satisfy the frozen runner semantics",
        )
        self.assertEqual(
            [],
            self.casefile.validate_casefile(artifact),
            "a frozen runner witness must also be legal under the current validator",
        )

    def test_bidirectional_interpretation_contract_is_satisfiable(self):
        case_id = "bidirectional-evidence-on-one-claim"
        artifact = self.standard_draft(
            case_id,
            unknown_type="formal_role_or_authority_change",
            user_decision="evidence_threshold",
        )
        proposition_span = self.span(artifact, "P1", "公司已经决定架空我。")
        proposition = self.claim(
            "C1",
            proposition_span,
            kind="interpretation",
            source_type="user_report",
            epistemic_status="conflicted",
        )
        artifact["claims"] = [proposition]

        evidence_specs = (
            (
                "E1",
                self.span(
                    artifact,
                    "E1",
                    "我连续三次没有被邀请参加岗位说明中写明“项目负责人必须参加”的决策会。",
                ),
                "user_direct_observation",
                "supports",
            ),
            (
                "E2",
                self.span(
                    artifact,
                    "E2",
                    "今天经理给我的书面职责确认仍写着“项目负责人”，",
                ),
                "unverified_artifact",
                "conflicts",
            ),
            (
                "E3",
                self.span(
                    artifact,
                    "E3",
                    "财务系统今天仍允许我审批该项目预算。",
                ),
                "user_direct_observation",
                "conflicts",
            ),
        )
        for evidence_id, span, source_type, relation in evidence_specs:
            self.attach_evidence(
                artifact,
                proposition,
                evidence_id,
                span,
                source_type=source_type,
                relation=relation,
            )

        fact_specs = (
            ("C2", "FE1", evidence_specs[0][1], "user_direct_observation"),
            ("C3", "FE2", evidence_specs[1][1], "unverified_artifact"),
            (
                "C4",
                "FE3",
                self.span(artifact, "E2", "并保留预算审批职责。"),
                "unverified_artifact",
            ),
            ("C5", "FE4", evidence_specs[2][1], "user_direct_observation"),
        )
        for claim_id, evidence_id, span, source_type in fact_specs:
            claim = self.claim(
                claim_id,
                span,
                kind="observable_fact",
                source_type=source_type,
                epistemic_status="reported",
                observation_type=self.casefile.derive_observation_type(
                    span["text"], span
                ),
            )
            artifact["claims"].append(claim)
            self.attach_evidence(
                artifact,
                claim,
                evidence_id,
                span,
                source_type=source_type,
                relation="supports",
            )

        self.assert_joint_contract(case_id, artifact)

    def test_long_anchor_fact_layer_refs_are_satisfiable(self):
        case_id = "long-narrative-exact-anchor"
        artifact = self.standard_draft(
            case_id,
            unknown_type="formal_role_or_authority_change",
            user_decision="employment_continuation",
        )
        claim_specs = (
            (
                "S3",
                "我打开项目日历，",
                "observable_fact",
                "user_direct_observation",
                "reported",
                "artifact_or_system_state",
            ),
            (
                "S4",
                "小林对我说：“我感觉老板可能想换人。”",
                "interpretation",
                "secondhand",
                "unverified",
                None,
            ),
            (
                "S5",
                "老板没有说过“你能力不行”。",
                "observable_fact",
                "user_direct_observation",
                "reported",
                "negative_report_event",
            ),
            (
                "S6",
                "我现在很害怕，",
                "explicit_feeling",
                "explicit_self_report",
                "reported",
                None,
            ),
            (
                "S7",
                "他就是嫌我能力差，",
                "interpretation",
                "user_report",
                "unverified",
                None,
            ),
        )
        for index, (
            source_ref,
            exact_text,
            kind,
            source_type,
            status,
            observation_type,
        ) in enumerate(claim_specs, start=1):
            span = self.span(artifact, source_ref, exact_text)
            claim = self.claim(
                f"C{index}",
                span,
                kind=kind,
                source_type=source_type,
                epistemic_status=status,
                observation_type=observation_type,
            )
            artifact["claims"].append(claim)
            relation = (
                "supports"
                if kind in {"observable_fact", "stated_position", "explicit_feeling"}
                else "does_not_establish"
            )
            self.attach_evidence(
                artifact,
                claim,
                f"E{index}",
                span,
                source_type=source_type,
                relation=relation,
            )

        material_span = self.span(
            artifact,
            "S2",
            "这次你先不用参加，我和销售把数字对一下。",
        )
        artifact["evidence"].append(
            {
                "id": "EM1",
                "input_id": material_span["input_id"],
                "source_span_id": material_span["id"],
                "source_ref": material_span["source_ref"],
                "source_type": "unverified_artifact",
                "exact_quote": material_span["text"],
                "can_establish": [],
                "cannot_establish": ["C5"],
                "limitations": ["artifact_not_verified", "missing_context"],
            }
        )
        artifact["evidence_links"].append(
            {
                "proposition_id": "C5",
                "evidence_ref": "EM1",
                "relation": "does_not_establish",
                "strength": "none",
                "reason": "source_scope_limit",
            }
        )

        missing_fact_span = self.span(
            artifact, "S3", "没有看到自己的名字。"
        )
        missing_fact = self.claim(
            "C7",
            missing_fact_span,
            kind="observable_fact",
            source_type="user_direct_observation",
            epistemic_status="reported",
            observation_type="artifact_or_system_state",
        )
        artifact["claims"].append(missing_fact)
        self.attach_evidence(
            artifact,
            missing_fact,
            "E7",
            missing_fact_span,
            source_type="user_direct_observation",
            relation="supports",
        )

        self.assert_joint_contract(case_id, artifact)

    def test_claim_specific_current_quote_contract_is_satisfiable(self):
        case_id = "claim-specific-strength-calibration"
        artifact = self.standard_draft(
            case_id,
            unknown_type="future_behavior_or_outcome",
            user_decision="relationship_continuation",
            action_type="pause_major_decision",
        )
        claim_specs = (
            (
                "我不想再继续约会，也不会参加周六的见面。",
                "stated_position",
                "direct_quote",
                "directly_stated",
                False,
            ),
            (
                "2. 他从来没有爱过我；",
                "motive_inference",
                "user_report",
                "unverified",
                False,
            ),
            (
                "3. 他是回避型人格；",
                "identity_claim",
                "user_report",
                "unverified",
                True,
            ),
            (
                "4. 他以后绝不会再联系我？",
                "prediction",
                "user_report",
                "unverified",
                False,
            ),
        )
        for index, (
            exact_text,
            kind,
            source_type,
            status,
            diagnostic_boundary,
        ) in enumerate(claim_specs, start=1):
            span = self.span(artifact, "input", exact_text)
            claim = self.claim(
                f"C{index}",
                span,
                kind=kind,
                source_type=source_type,
                epistemic_status=status,
                diagnostic_boundary=diagnostic_boundary,
            )
            artifact["claims"].append(claim)
            relation = "supports" if kind == "stated_position" else "does_not_establish"
            self.attach_evidence(
                artifact,
                claim,
                f"E{index}",
                span,
                source_type=source_type,
                relation=relation,
            )

        self.assert_joint_contract(case_id, artifact)


if __name__ == "__main__":
    unittest.main()
