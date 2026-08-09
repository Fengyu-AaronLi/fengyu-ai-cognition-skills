#!/usr/bin/env python3
"""Rebuild the checked-in executable demo without calling a language model."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
SOURCE_DIR = ROOT / "examples" / "real-run"
RUNTIME_ARTIFACTS = (
    ".case.lock",
    "case.json",
    "events.jsonl",
    "events.head.json",
    "report.md",
)
PUBLISHED_ARTIFACTS = (*RUNTIME_ARTIFACTS, "run-manifest.json")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed: identity_label_case.py {' '.join(args)}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def shifted_clock(value: str, delta: timedelta) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("demo clock must include an explicit timezone")
    shifted = (parsed.astimezone(timezone.utc) + delta).isoformat(timespec="seconds")
    return shifted.replace("+00:00", "Z")


def build(output_dir: Path, clock: str) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    input_path = SOURCE_DIR / "demo-input.txt"
    analysis_path = SOURCE_DIR / "analysis.json"
    clocks = {
        "init": shifted_clock(clock, timedelta()),
        "plan": shifted_clock(clock, timedelta(minutes=1)),
        "start": shifted_clock(clock, timedelta(minutes=2)),
        "record": shifted_clock(clock, timedelta(days=1, minutes=2)),
        "record_retry": shifted_clock(clock, timedelta(days=1, minutes=3)),
        "review": shifted_clock(clock, timedelta(days=14, minutes=3)),
    }
    operation_id = "demo-record-001"
    result_text = "实验第一天，我用十五分钟整理后，当天提出了一份可修改的分工初版，对方确认能够执行。"
    result_fact = "当天提出了一份可修改的分工初版"
    review_rationale = "一次按预注册条件完成的任务削弱了“有准备时间仍无法提出分工初版”这一窄命题，但不能定义人格。"
    confirmation_text = "我愿意开始这个十四天的单变量现实实验。"
    recorded_commands = [
        ["init", "--text-file", "examples/real-run/demo-input.txt", "--case-dir", "<demo-run>", "--case-id", "demo-ai-label", "--clock", clocks["init"]],
        ["plan", "--case-dir", "<demo-run>", "--analysis", "examples/real-run/analysis.json", "--clock", clocks["plan"]],
        [
            "start", "--case-dir", "<demo-run>",
            "--confirmation-file", "<demo-run>/user-confirmation.txt",
            "--clock", clocks["start"],
        ],
        [
            "record", "--case-dir", "<demo-run>", "--kind", "experiment_result",
            "--observation-file", "<demo-run>/observation.json",
            "--operation-id", operation_id, "--clock", clocks["record"],
        ],
        [
            "record", "--case-dir", "<demo-run>", "--kind", "experiment_result",
            "--observation-file", "<demo-run>/observation.json",
            "--operation-id", operation_id, "--clock", clocks["record_retry"],
        ],
        [
            "review", "--case-dir", "<demo-run>", "--classification", "weakens",
            "--rationale-file", "<demo-run>/rationale.txt", "--clock", clocks["review"],
        ],
        ["validate", "<demo-run>/case.json"],
        ["replay", "--case-dir", "<demo-run>"],
        ["render", "<demo-run>/case.json", "--out", "<demo-run>/report.md"],
    ]
    with tempfile.TemporaryDirectory(prefix="identity-label-demo-") as temporary:
        run_dir = Path(temporary) / "run"
        observation_path = Path(temporary) / "observation.json"
        observation_path.write_text(
            json.dumps(
                {
                    "source_text": result_text,
                    "fact": result_fact,
                    "context": "团队分工任务",
                    "timeframe": "实验第一天",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        rationale_path = Path(temporary) / "rationale.txt"
        rationale_path.write_text(review_rationale, encoding="utf-8")
        confirmation_path = Path(temporary) / "user-confirmation.txt"
        confirmation_path.write_text(confirmation_text, encoding="utf-8")
        run_cli(
            "init",
            "--text-file",
            str(input_path),
            "--case-dir",
            str(run_dir),
            "--case-id",
            "demo-ai-label",
            "--clock",
            clocks["init"],
        )
        run_cli(
            "plan",
            "--case-dir",
            str(run_dir),
            "--analysis",
            str(analysis_path),
            "--clock",
            clocks["plan"],
        )
        run_cli(
            "start",
            "--case-dir",
            str(run_dir),
            "--confirmation-file",
            str(confirmation_path),
            "--clock",
            clocks["start"],
        )
        run_cli(
            "record",
            "--case-dir",
            str(run_dir),
            "--kind",
            "experiment_result",
            "--observation-file",
            str(observation_path),
            "--operation-id",
            operation_id,
            "--clock",
            clocks["record"],
        )
        retry = json.loads(
            run_cli(
                "record",
                "--case-dir",
                str(run_dir),
                "--kind",
                "experiment_result",
                "--observation-file",
                str(observation_path),
                "--operation-id",
                operation_id,
                "--clock",
                clocks["record_retry"],
            ).stdout
        )
        run_cli(
            "review",
            "--case-dir",
            str(run_dir),
            "--classification",
            "weakens",
            "--rationale-file",
            str(rationale_path),
            "--clock",
            clocks["review"],
        )
        validation = json.loads(run_cli("validate", str(run_dir / "case.json")).stdout)
        replay = json.loads(run_cli("replay", "--case-dir", str(run_dir)).stdout)
        run_cli("render", str(run_dir / "case.json"), "--out", str(run_dir / "report.md"))
        case = json.loads((run_dir / "case.json").read_text(encoding="utf-8"))
        for name in RUNTIME_ARTIFACTS:
            shutil.copyfile(run_dir / name, output_dir / name)

    manifest = {
        "schema_version": "2.0",
        "package_version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "run_type": "deterministic_runtime_demo",
        "model": None,
        "model_note": "No model call. Semantic analysis is a checked-in fixture; runtime routing, validation, state and rendering are replayed.",
        "clock": clock,
        "clocks": clocks,
        "skill_sha256": sha256(ROOT / "SKILL.md"),
        "runtime_sha256": sha256(CLI),
        "input_sha256": sha256(input_path),
        "analysis_sha256": sha256(analysis_path),
        "idempotency": {
            "operation_id": operation_id,
            "retry_returned_original": retry.get("idempotent_replay") is True,
            "retry_revision": retry.get("case", {}).get("revision"),
        },
        "commands": recorded_commands,
        "validation": validation,
        "replay": replay,
        "final_status": case["status"],
        "artifacts": {name: sha256(output_dir / name) for name in RUNTIME_ARTIFACTS},
    }
    (output_dir / "run-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def publish(staging_dir: Path, output_dir: Path, *, force: bool) -> None:
    """Publish known generated files atomically and leave unknown files untouched."""

    if output_dir.exists():
        if output_dir.is_symlink() or not output_dir.is_dir():
            raise ValueError("demo output must be a regular directory")
        if not force:
            raise ValueError("demo output directory already exists; pass --force to rebuild")
    else:
        output_dir.mkdir(parents=True)
    for name in PUBLISHED_ARTIFACTS:
        source = staging_dir / name
        with tempfile.NamedTemporaryFile(
            prefix=f".{name}.",
            suffix=".tmp",
            dir=output_dir,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(source.read_bytes())
            handle.flush()
        try:
            temporary.replace(output_dir / name)
        finally:
            if temporary.exists():
                temporary.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SOURCE_DIR,
        help="Directory for generated case, events, report and manifest",
    )
    parser.add_argument("--clock", default="2026-08-06T10:00:00Z")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace only known generated artifacts in an existing output directory",
    )
    args = parser.parse_args()
    try:
        output_dir = args.output_dir.resolve()
        if output_dir.exists() and not args.force:
            raise ValueError("demo output directory already exists; pass --force to rebuild")
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="identity-label-demo-publish-",
            dir=output_dir.parent,
        ) as temporary:
            staging_dir = Path(temporary) / "generated"
            manifest = build(staging_dir, args.clock)
            publish(staging_dir, output_dir, force=args.force)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, ensure_ascii=False))
        raise SystemExit(1)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
