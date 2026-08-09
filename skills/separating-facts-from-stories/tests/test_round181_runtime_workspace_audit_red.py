#!/usr/bin/env python3
"""Round 181 RED: the independent auditor rechecks host-managed workspace evidence."""

from __future__ import annotations

import importlib.util
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
AUDITOR_PATH = SKILL_DIR / "scripts" / "run_evals.py"
ROUND176_PATH = SKILL_DIR / "tests" / "test_round176_host_artifact_promotion_red.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Round181RuntimeWorkspaceAuditRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.auditor = load(AUDITOR_PATH, "round181_eval_auditor")
        cls.round176 = load(ROUND176_PATH, "round181_round176_fixture")
        cls.round176.Round176HostArtifactPromotionRedTests.setUpClass()

    def completed_case(self, temp: Path) -> tuple[Path, Path, str]:
        helper = self.round176.Round176HostArtifactPromotionRedTests()
        case_id = "relationship-silence"
        root = temp / "eval"
        helper.auditor.prepare_root(root)
        workspace, message = helper.completed_workspace(root, case_id)
        receipt = helper.host_receipt(root, case_id, message.rstrip("\n"), temp)
        helper.host.bind_eval_case_result(
            receipt_path=receipt,
            eval_root=root,
            case_id=case_id,
        )
        baseline = self.auditor.audit_case_result(
            root, case_id, self.auditor.EXPECTED_CASES[case_id]
        )
        self.assertTrue(baseline["valid"], baseline)
        return root, workspace, case_id

    def test_auditor_rejects_post_bind_raw_input_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round181-input-") as temp_dir:
            root, _, case_id = self.completed_case(Path(temp_dir))
            raw_input = root / case_id / ".runtime/input-1.txt"
            raw_input.chmod(stat.S_IRUSR | stat.S_IWUSR)
            raw_input.write_text("被篡改的输入", encoding="utf-8")

            audit = self.auditor.audit_case_result(
                root, case_id, self.auditor.EXPECTED_CASES[case_id]
            )

            self.assertIn(
                "RUNTIME_INPUT_MISMATCH",
                {item["code"] for item in audit["errors"]},
                audit,
            )

    def test_auditor_rejects_second_internal_casefile_after_binding(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round181-extra-") as temp_dir:
            root, workspace, case_id = self.completed_case(Path(temp_dir))
            alternate = root / case_id / ".runtime/workspace-evil"
            alternate.mkdir()
            shutil.copyfile(workspace / "casefile.json", alternate / "casefile.json")

            audit = self.auditor.audit_case_result(
                root, case_id, self.auditor.EXPECTED_CASES[case_id]
            )

            self.assertIn(
                "RUNTIME_CASEFILE_SET_MISMATCH",
                {item["code"] for item in audit["errors"]},
                audit,
            )

    def test_auditor_rejects_internal_canonical_divergence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round181-diverge-") as temp_dir:
            root, workspace, case_id = self.completed_case(Path(temp_dir))
            internal = workspace / "casefile.json"
            internal.write_text("{}\n", encoding="utf-8")

            audit = self.auditor.audit_case_result(
                root, case_id, self.auditor.EXPECTED_CASES[case_id]
            )

            self.assertIn(
                "RUNTIME_CANONICAL_ARTIFACT_MISMATCH",
                {item["code"] for item in audit["errors"]},
                audit,
            )


if __name__ == "__main__":
    unittest.main()
