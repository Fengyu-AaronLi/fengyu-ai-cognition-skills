#!/usr/bin/env python3
"""V73 red contracts for durable blockers and atomic release-state updates."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts" / "run_evolution.py"


def load_v11_fixture_module():
    path = ROOT / "tests" / "test_v11_evolution_controller.py"
    spec = importlib.util.spec_from_file_location("identity_v11_fixture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("v11_fixture_import_failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V11 = load_v11_fixture_module()
EvolutionFixture = V11.EvolutionFixture
AUDIT_IDS = V11.AUDIT_IDS


def make_fixture(root: Path):
    fixture = EvolutionFixture(root)
    (root / "examples" / "real-run" / ".case.lock").write_text(
        "fixture lock\n",
        encoding="utf-8",
    )
    return fixture


class V73ReleaseStateMemoryAndConcurrencyTests(unittest.TestCase):
    def test_new_root_run_cannot_bypass_open_release_blockers(self) -> None:
        """An open release blocker forces lineage through next-iteration."""

        with tempfile.TemporaryDirectory(prefix="identity-v73-root-blocker-") as temp:
            fixture = make_fixture(Path(temp))
            fixture.write_state(passed=False)
            run_dir = fixture.root / "evals" / "runs" / "v73-forgotten-root"

            result = fixture.controller(
                "run",
                "--workflow",
                str(fixture.workflow_path),
                "--run-dir",
                str(run_dir),
                "--run-id",
                "v73-forgotten-root",
                "--candidate-id",
                "v73-forgotten-root",
            )

            self.assertNotEqual(
                0,
                result.returncode,
                "A fresh root run silently bypassed an open release blocker.\n"
                + result.stdout
                + result.stderr,
            )
            self.assertFalse(
                run_dir.exists(),
                "Rejected root runs must not leave a new run projection behind.",
            )

    def test_freeze_cannot_erase_blockers_from_the_previous_release_state(self) -> None:
        """A freeze either refuses or preserves every unresolved blocker."""

        with tempfile.TemporaryDirectory(prefix="identity-v73-freeze-blocker-") as temp:
            fixture = make_fixture(Path(temp))
            completed_run = fixture.complete_run(
                "v73-new-candidate",
                "v73-new-candidate-run",
            )
            fixture.write_state(passed=False)
            before_bytes = fixture.state_path.read_bytes()
            before = json.loads(before_bytes)
            unresolved_ids = {item["id"] for item in before["blockers"]}
            self.assertTrue(unresolved_ids)

            result = fixture.controller(
                "freeze",
                "--candidate-id",
                "v73-new-candidate",
                "--workflow",
                str(fixture.workflow_path),
                "--completed-run-dir",
                str(completed_run),
                "--clock",
                "2026-08-07T03:00:00Z",
            )

            if result.returncode != 0:
                self.assertEqual(
                    before_bytes,
                    fixture.state_path.read_bytes(),
                    "A refused freeze still mutated the previous release state.",
                )
            else:
                after = json.loads(fixture.state_path.read_text(encoding="utf-8"))
                after_ids = {item["id"] for item in after["blockers"]}
                self.assertTrue(
                    unresolved_ids.issubset(after_ids),
                    "A successful freeze forgot unresolved blockers from the previous "
                    f"release state: before={sorted(unresolved_ids)}, "
                    f"after={sorted(after_ids)}",
                )

    def test_concurrent_audit_writes_never_report_success_then_lose_an_update(self) -> None:
        """All successful concurrent audit writes survive, or fail with conflict."""

        with tempfile.TemporaryDirectory(prefix="identity-v73-audit-race-") as temp:
            fixture = make_fixture(Path(temp))
            # Keep all workers in the validation phase long enough to read the same
            # generation before any one of them publishes its update.
            (fixture.root / "scripts" / "identity_label_case.py").write_bytes(
                b"# fixture runtime\n" + (b"x" * (32 * 1024 * 1024))
            )
            fixture.write_state(passed=True)
            state = json.loads(fixture.state_path.read_text(encoding="utf-8"))
            state["audits"] = [
                {
                    "audit_id": audit_id,
                    "artifact_sha256": None,
                    "blocker_count": 0,
                    "evidence": [],
                    "receipt_sha256": None,
                    "status": "pending",
                }
                for audit_id in AUDIT_IDS
            ]
            state["blockers"] = []
            state["blocker_count"] = 0
            state["decision"] = "pending"
            V11.write_json(fixture.state_path, state)

            gate = fixture.root / "evals" / ".v73-start-gate"
            launcher = (
                "import json, os, pathlib, sys, time; "
                "gate = pathlib.Path(sys.argv[1]); "
                "argv = json.loads(sys.argv[2]); "
                "deadline = time.monotonic() + 10; "
                "\nwhile not gate.exists():\n"
                "    if time.monotonic() > deadline: raise SystemExit(98)\n"
                "    time.sleep(0.001)\n"
                "os.execv(argv[0], argv)"
            )
            processes: list[tuple[str, subprocess.Popen[str]]] = []
            for audit_id in AUDIT_IDS:
                argv = [
                    sys.executable,
                    str(CONTROLLER),
                    "record-audit",
                    "--receipt",
                    f"evals/receipts/{audit_id}.json",
                    "--root",
                    str(fixture.root),
                    "--state",
                    str(fixture.state_path),
                    "--test-manifest",
                    str(fixture.manifest_path),
                ]
                process = subprocess.Popen(
                    [sys.executable, "-c", launcher, str(gate), json.dumps(argv)],
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                processes.append((audit_id, process))

            time.sleep(0.05)
            gate.touch()
            outcomes: dict[str, tuple[int, str]] = {}
            for audit_id, process in processes:
                stdout, stderr = process.communicate(timeout=30)
                outcomes[audit_id] = (process.returncode, stdout + stderr)

            successful = {
                audit_id
                for audit_id, (returncode, _) in outcomes.items()
                if returncode == 0
            }
            self.assertTrue(successful, outcomes)
            allowed_conflicts = (
                "release_state_locked",
                "release_state_conflict",
                "release_state_stale",
            )
            for audit_id, (returncode, output) in outcomes.items():
                if returncode != 0:
                    self.assertTrue(
                        any(marker in output for marker in allowed_conflicts),
                        f"{audit_id} failed without an explicit concurrency outcome:\n{output}",
                    )

            final_state = json.loads(fixture.state_path.read_text(encoding="utf-8"))
            recorded = {
                item["audit_id"]
                for item in final_state["audits"]
                if item["status"] == "passed"
            }
            outcome_codes = {
                audit_id: returncode
                for audit_id, (returncode, _) in outcomes.items()
            }
            self.assertTrue(
                successful.issubset(recorded),
                "The CLI reported successful audit writes that disappeared from the "
                f"final state: successful={sorted(successful)}, "
                f"recorded={sorted(recorded)}, returncodes={outcome_codes}",
            )

    def test_freeze_and_blocked_audit_share_one_atomic_state_generation(self) -> None:
        """A concurrent freeze cannot erase a successfully recorded audit blocker."""

        with tempfile.TemporaryDirectory(prefix="identity-v73-freeze-audit-race-") as temp:
            fixture = make_fixture(Path(temp))
            (fixture.root / "scripts" / "identity_label_case.py").write_bytes(
                b"# fixture runtime\n" + (b"x" * (32 * 1024 * 1024))
            )
            fixture.write_state(passed=True)
            state = json.loads(fixture.state_path.read_text(encoding="utf-8"))
            state["audits"] = [
                {
                    "audit_id": audit_id,
                    "artifact_sha256": None,
                    "blocker_count": 0,
                    "evidence": [],
                    "receipt_sha256": None,
                    "status": "pending",
                }
                for audit_id in AUDIT_IDS
            ]
            state["blockers"] = []
            state["blocker_count"] = 0
            state["decision"] = "pending"
            V11.write_json(fixture.state_path, state)

            audit_id = "independent_state_integrity_audit"
            receipt_path = fixture.root / "evals" / "receipts" / f"{audit_id}.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["blockers"] = [{"id": "v73-race-blocker", "severity": "P0"}]
            receipt["status"] = "blocked"
            V11.write_json(receipt_path, receipt)

            completed_run = fixture.root / "evals" / "runs" / "v11-fixture-run"
            audit_argv = [
                sys.executable,
                str(CONTROLLER),
                "record-audit",
                "--receipt",
                f"evals/receipts/{audit_id}.json",
                "--root",
                str(fixture.root),
                "--state",
                str(fixture.state_path),
                "--test-manifest",
                str(fixture.manifest_path),
            ]
            freeze_argv = [
                sys.executable,
                str(CONTROLLER),
                "freeze",
                "--candidate-id",
                "v11-fixture",
                "--workflow",
                str(fixture.workflow_path),
                "--completed-run-dir",
                str(completed_run),
                "--clock",
                "2026-08-07T03:30:00Z",
                "--root",
                str(fixture.root),
                "--state",
                str(fixture.state_path),
                "--test-manifest",
                str(fixture.manifest_path),
            ]
            gate = fixture.root / "evals" / ".v73-freeze-audit-start-gate"
            launcher = (
                "import json, os, pathlib, sys, time; "
                "gate = pathlib.Path(sys.argv[1]); "
                "argv = json.loads(sys.argv[2]); "
                "deadline = time.monotonic() + 10; "
                "\nwhile not gate.exists():\n"
                "    if time.monotonic() > deadline: raise SystemExit(98)\n"
                "    time.sleep(0.001)\n"
                "os.execv(argv[0], argv)"
            )
            processes = {
                "audit": subprocess.Popen(
                    [sys.executable, "-c", launcher, str(gate), json.dumps(audit_argv)],
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                ),
                "freeze": subprocess.Popen(
                    [sys.executable, "-c", launcher, str(gate), json.dumps(freeze_argv)],
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                ),
            }
            time.sleep(0.05)
            gate.touch()
            outcomes: dict[str, tuple[int, str]] = {}
            for name, process in processes.items():
                stdout, stderr = process.communicate(timeout=30)
                outcomes[name] = (process.returncode, stdout + stderr)

            allowed_conflicts = (
                "release_state_locked",
                "release_state_conflict",
                "release_state_stale",
                "release_state_open_blockers",
            )
            for name, (returncode, output) in outcomes.items():
                if returncode != 0:
                    self.assertTrue(
                        any(marker in output for marker in allowed_conflicts),
                        f"{name} failed without an explicit concurrency outcome:\n{output}",
                    )

            final_state = json.loads(fixture.state_path.read_text(encoding="utf-8"))
            blocker_ids = {item["id"] for item in final_state["blockers"]}
            expected_blocker = f"{audit_id}:v73-race-blocker"
            audit_succeeded = outcomes["audit"][0] == 0
            outcome_codes = {
                name: returncode for name, (returncode, _) in outcomes.items()
            }
            self.assertTrue(audit_succeeded or outcomes["freeze"][0] == 0, outcomes)
            if audit_succeeded:
                self.assertIn(
                    expected_blocker,
                    blocker_ids,
                    "The blocked audit reported success, but a concurrent freeze erased "
                    f"its blocker: returncodes={outcome_codes}, "
                    f"final_decision={final_state['decision']}, "
                    f"final_blockers={sorted(blocker_ids)}",
                )


if __name__ == "__main__":
    unittest.main()
