from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
REAL_LEGACY_DIR = (
    SKILL_DIR
    / "evals"
    / "raw"
    / "with-skill-v30-failed-attempts"
    / "round129-versioned-update-red-v401"
    / "long-narrative-exact-anchor"
)
REAL_LEGACY_PATH = REAL_LEGACY_DIR / "artifacts" / "separation.json"
REAL_RECEIPT_PATH = REAL_LEGACY_DIR / "receipts" / "validation.json"
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


def _passthrough_root() -> dict[str, Any]:
    return casefile.make_draft(
        "只翻译成英文：你好。", "round133-version-graph", "passthrough"
    )


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


def _revision(previous: dict[str, Any], text: str) -> dict[str, Any]:
    pair = casefile._casefile_version_pair(previous)
    return casefile.start_update(
        previous,
        text,
        legacy_receipt=(
            _legacy_receipt(previous)
            if pair in casefile.MIGRATABLE_VERSION_PAIRS
            else None
        ),
    )


def _attributed_statement_410() -> dict[str, Any]:
    text = "他回复：‘手机送修，刚拿回来’。"
    draft = casefile.make_draft(text, "round133-attributed-410", "standard")
    span = max(
        (item for item in draft["source_spans"] if item.get("quoted") is True),
        key=lambda item: len(item["text"]),
    )
    draft["claims"] = [
        {
            "id": "C1",
            "kind": "attributed_statement",
            "text": span["text"],
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "direct_quote",
            "exact_quote": span["text"],
            "epistemic_status": "directly_stated",
            "diagnostic_boundary": False,
        }
    ]
    draft["evidence"] = [
        {
            "id": "E1",
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "direct_quote",
            "exact_quote": span["text"],
            "can_establish": ["C1"],
            "cannot_establish": [],
            "limitations": ["single_party_report"],
        }
    ]
    draft["evidence_links"] = [
        {
            "proposition_id": "C1",
            "evidence_ref": "E1",
            "relation": "supports",
            "strength": "direct",
            "reason": "anchor_matches_report",
        }
    ]
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
    draft["schema_version"] = "3.1.0"
    draft["skill_version"] = "4.1.0"
    return draft


class Round133VersionMigrationGraphRedTests(unittest.TestCase):
    """Supported version pairs still require a monotonic history edge."""

    def test_current_to_legacy_downgrade_is_rejected(self) -> None:
        current = _passthrough_root()
        downgraded = _revision(current, "只翻译成英文：再见。")
        downgraded["schema_version"] = "3.0.0"
        downgraded["skill_version"] = "4.0.0"
        self.assertIn(
            "VERSION_MIGRATION_DIRECTION_INVALID",
            {
                item["code"]
                for item in casefile.validate_casefile(
                    downgraded,
                    previous=current,
                    legacy_receipt=_legacy_receipt(downgraded),
                )
            },
        )

    def test_legacy_history_may_only_move_forward(self) -> None:
        legacy = json.loads(REAL_LEGACY_PATH.read_text(encoding="utf-8"))
        receipt = json.loads(REAL_RECEIPT_PATH.read_text(encoding="utf-8"))

        current = casefile.start_update(
            legacy,
            "我看到门口多了一把钥匙。",
            legacy_receipt=receipt,
        )
        self.assertEqual(
            [],
            casefile.validate_casefile(
                current,
                previous=legacy,
                legacy_receipt=receipt,
            ),
        )

        legacy_downgrade = casefile.start_update(
            legacy,
            "我看到桌上多了一张便签。",
            legacy_receipt=receipt,
        )
        legacy_downgrade["schema_version"] = "3.0.0"
        legacy_downgrade["skill_version"] = "4.0.0"
        self.assertIn(
            "VERSION_MIGRATION_DIRECTION_INVALID",
            {
                item["code"]
                for item in casefile.validate_casefile(
                    legacy_downgrade,
                    previous=legacy,
                    legacy_receipt=_legacy_receipt(legacy_downgrade),
                )
            },
        )

    def test_workflow_rejects_a_current_to_legacy_history_chain(self) -> None:
        current = _passthrough_root()
        downgraded = _revision(current, "只翻译成英文：再见。")
        downgraded["schema_version"] = "3.0.0"
        downgraded["skill_version"] = "4.0.0"

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            revision_1 = root / "revision-1.json"
            revision_2 = root / "revision-2.json"
            input_path = root / "input.txt"
            receipt_path = root / "legacy-receipt.json"
            workspace = root / "workspace"
            revision_1.write_text(
                json.dumps(current, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            revision_2.write_text(
                json.dumps(downgraded, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            input_path.write_text("只翻译成英文：谢谢。", encoding="utf-8")
            receipt_path.write_text(
                json.dumps(
                    _legacy_receipt(downgraded),
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
                    str(revision_1),
                    str(revision_2),
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

    def test_unattested_410_attributed_statement_history_is_blocked(self) -> None:
        previous = _attributed_statement_410()
        codes = {
            item["code"]
            for item in casefile.validate_casefile(previous)
        }
        self.assertIn("VERSION_PAIR_UNSUPPORTED", codes)
        with self.assertRaisesRegex(ValueError, "unsupported previous version pair"):
            casefile.start_update(
                previous,
                "只翻译成英文：谢谢。",
            )


if __name__ == "__main__":
    unittest.main()
