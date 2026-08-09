#!/usr/bin/env python3
"""Fixed worker actions for the controller-owned improvement graph.

This program accepts only named actions implemented in this file.  It never
accepts a shell command, arbitrary argv tail, or user supplied Python code.
The parent controller treats stdout as untrusted worker output and derives its
own process receipt before accepting a phase result.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "graph_worker_bundle.v1"
SUPPORTED_STEPS = {"preflight_snapshot"}


def _read_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} is not a regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def run_preflight(state: dict[str, Any], work_order: dict[str, Any]) -> dict[str, Any]:
    if work_order.get("step_id") != "preflight_snapshot":
        raise ValueError("work order does not authorize preflight_snapshot")
    controller_path = state["workflow_policy"]["controller_executable"]
    tests_root = str(Path(controller_path).parents[1] / "tests")
    return {
        "schema_version": SCHEMA_VERSION,
        "step_id": "preflight_snapshot",
        "summary": "Controller-owned preflight snapshot completed.",
        "result": {
            "source_file_count": len(state["source_files"]),
            "source_manifest_sha256": state["source_manifest"]["sha256"],
            "workflow_sha256": state["workflow"]["sha256"],
            "controller_sha256": state["source_snapshot"]["files"][controller_path],
            "tests_root": tests_root,
            "protected_changes": [],
            "denied_operations": sorted(
                state["workflow_policy"]["denied_operations"]
            ),
        },
        "finding_events": [],
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--step", choices=sorted(SUPPORTED_STEPS), required=True)
    root.add_argument("--state", required=True)
    root.add_argument("--work-order", required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        state = _read_object(Path(args.state), "state")
        work_order = _read_object(Path(args.work_order), "work order")
        if args.step == "preflight_snapshot":
            bundle = run_preflight(state, work_order)
        else:  # pragma: no cover, argparse owns the closed action set
            raise ValueError("unsupported fixed graph step")
        print(json.dumps(bundle, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, UnicodeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
