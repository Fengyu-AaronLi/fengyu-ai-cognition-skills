from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


DIRECT_ACCOUNT = "手机送修，刚拿回来"
DISALLOWED_ATTRIBUTIONS = (
    "他说：‘手机究竟有没有送修。’",
    "据同事说，他原话是：‘手机送修，刚拿回来’。",
    "朋友发截图说这是他的原话：‘手机送修，刚拿回来’。",
    "朋友替他说：‘手机送修，刚拿回来’。",
    "案例中他说：‘手机送修，刚拿回来’。",
    "我梦见他回复：‘手机送修，刚拿回来’。",
    "语法分析：他说‘手机送修，刚拿回来’。",
    "他说同事告诉他：‘手机送修，刚拿回来’。",
    "他说：“手机送修，刚拿回来”，接着表示这句话不作数。",
)


def _standard_shell(text: str, case_id: str) -> dict[str, Any]:
    draft = casefile.make_draft(text, case_id, "standard")
    draft["unknowns"] = [
        {
            "id": "U1",
            "unknown_type": "event_cause_or_context",
            "text": casefile.UNKNOWN_CATALOG["event_cause_or_context"],
            "status": "open",
            "resolved_by_evidence_refs": [],
        }
    ]
    action = {
        key: value
        for key, value in casefile.ACTION_CATALOG["neutral_check"].items()
        if key != "modes"
    }
    draft["actions"] = [{"id": "A1", "action_type": "neutral_check", **action}]
    draft["user_decisions"] = ["evidence_threshold"]
    return draft


def _full_quote_span(draft: dict[str, Any]) -> dict[str, Any]:
    quoted = [item for item in draft["source_spans"] if item.get("quoted") is True]
    return max(quoted, key=lambda item: len(item["text"]))


def _append_claim(
    draft: dict[str, Any],
    span: dict[str, Any],
    *,
    claim_id: str,
    evidence_id: str,
    kind: str,
    source_type: str,
    status: str,
    observation_type: str | None = None,
) -> None:
    claim = {
        "id": claim_id,
        "kind": kind,
        "text": span["text"],
        "input_id": span["input_id"],
        "source_span_id": span["id"],
        "source_ref": span["source_ref"],
        "source_type": source_type,
        "exact_quote": span["text"],
        "epistemic_status": status,
        "diagnostic_boundary": False,
    }
    if observation_type is not None:
        claim["observation_type"] = observation_type
    draft["claims"].append(claim)
    draft["evidence"].append(
        {
            "id": evidence_id,
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": source_type,
            "exact_quote": span["text"],
            "can_establish": [claim_id],
            "cannot_establish": [],
            "limitations": ["single_party_report"],
        }
    )
    draft["evidence_links"].append(
        {
            "proposition_id": claim_id,
            "evidence_ref": evidence_id,
            "relation": "supports",
            "strength": "direct",
            "reason": "anchor_matches_report",
        }
    )


def _valid_observation_revision() -> dict[str, Any]:
    draft = _standard_shell(
        "他看了消息六个小时没回。", "round131-legacy-history"
    )
    span = next(
        item
        for item in draft["source_spans"]
        if item["text"] == "他看了消息六个小时没回。"
    )
    _append_claim(
        draft,
        span,
        claim_id="C1",
        evidence_id="E1",
        kind="observable_fact",
        source_type="user_direct_observation",
        status="reported",
        observation_type="communication_event",
    )
    assert casefile.validate_casefile(draft) == []
    return draft


def _legacy_receipt(data: dict[str, Any]) -> dict[str, Any]:
    pair = casefile._casefile_version_pair(data)
    assert pair in casefile.MIGRATABLE_VERSION_PAIRS
    return {
        "valid": True,
        "error_count": 0,
        "errors": [],
        "casefile_sha256": casefile.canonical_sha256(data),
        "schema_version": pair[0],
        "validator_version": pair[1],
    }


class Round131AttributionBoundaryRedTests(unittest.TestCase):
    """Attribution requires direct real speech, not a quote-shaped string."""

    def test_disallowed_quote_contexts_do_not_derive_attributed_statement(self) -> None:
        for text in DISALLOWED_ATTRIBUTIONS:
            with self.subTest(text=text):
                draft = casefile.make_draft(text, "round131-boundary", "standard")
                span = _full_quote_span(draft)
                self.assertNotEqual(
                    "attributed_statement",
                    casefile.derive_claim_kind_for_span(span["text"], span, text),
                )

    def test_manual_attribution_in_disallowed_context_is_rejected(self) -> None:
        for text in DISALLOWED_ATTRIBUTIONS:
            with self.subTest(text=text):
                draft = _standard_shell(text, "round131-manual-rejection")
                span = _full_quote_span(draft)
                _append_claim(
                    draft,
                    span,
                    claim_id="C1",
                    evidence_id="E1",
                    kind="attributed_statement",
                    source_type="direct_quote",
                    status="directly_stated",
                )
                codes = {item["code"] for item in casefile.validate_casefile(draft)}
                self.assertTrue(
                    {
                        "CLAIM_KIND_NOT_DERIVED",
                        "DIRECT_QUOTE_NOT_ASSERTED",
                        "SOURCE_TYPE_MISMATCH",
                    }
                    & codes,
                    codes,
                )

    def test_direct_current_and_past_accounts_remain_attributed(self) -> None:
        for text in (
            "他回复：‘手机送修，刚拿回来’。",
            "去年他说：‘手机送修，刚拿回来’。",
        ):
            with self.subTest(text=text):
                draft = casefile.make_draft(text, "round131-positive", "standard")
                span = _full_quote_span(draft)
                self.assertEqual(
                    "attributed_statement",
                    casefile.derive_claim_kind_for_span(span["text"], span, text),
                )

    def test_past_direct_account_forms_a_valid_casefile(self) -> None:
        text = "去年他说：‘手机送修，刚拿回来’。"
        draft = _standard_shell(text, "round131-past-account")
        span = _full_quote_span(draft)
        _append_claim(
            draft,
            span,
            claim_id="C1",
            evidence_id="E1",
            kind="attributed_statement",
            source_type="direct_quote",
            status="directly_stated",
        )
        self.assertEqual([], casefile.validate_casefile(draft))

    def test_unattested_legacy_revision_cannot_start_a_current_update(self) -> None:
        previous = _valid_observation_revision()
        previous["schema_version"] = "3.0.0"

        for legacy_skill_version in ("4.0.0", "4.0.1"):
            with self.subTest(legacy_skill_version=legacy_skill_version):
                legacy = copy.deepcopy(previous)
                legacy["skill_version"] = legacy_skill_version
                receipt = _legacy_receipt(legacy)
                codes = {
                    item["code"]
                    for item in casefile.validate_casefile(
                        legacy, legacy_receipt=receipt
                    )
                }
                self.assertIn("LEGACY_ARTIFACT_NOT_ATTESTED", codes)
                with self.assertRaisesRegex(
                    ValueError, "LEGACY_ARTIFACT_NOT_ATTESTED"
                ):
                    casefile.start_update(
                        legacy,
                        "他回复了消息。",
                        legacy_receipt=receipt,
                    )

        mismatched = copy.deepcopy(previous)
        mismatched["skill_version"] = "4.1.0"
        self.assertIn(
            "VERSION_PAIR_UNSUPPORTED",
            {item["code"] for item in casefile.validate_casefile(mismatched)},
        )

    def test_workflow_start_update_rejects_unattested_legacy_history(self) -> None:
        previous = _valid_observation_revision()
        previous["schema_version"] = "3.0.0"
        previous["skill_version"] = "4.0.0"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            history = root / "revision-1.json"
            input_path = root / "input.txt"
            receipt_path = root / "legacy-receipt.json"
            workspace = root / "workspace"
            history.write_text(
                json.dumps(previous, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            input_path.write_text("他回复了消息。", encoding="utf-8")
            receipt_path.write_text(
                json.dumps(
                    _legacy_receipt(previous),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_DIR / "scripts" / "workflow.py"),
                    "start-update",
                    "--history",
                    str(history),
                    "--input",
                    str(input_path),
                    "--workspace",
                    str(workspace),
                    "--legacy-receipt",
                    str(receipt_path),
                    "--mode",
                    "auto",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(2, completed.returncode)
            self.assertIn("HISTORY_INVALID", completed.stderr)
            self.assertIn("LEGACY_ARTIFACT_NOT_ATTESTED", completed.stderr)


if __name__ == "__main__":
    unittest.main()
