#!/usr/bin/env python3
"""Generate and execute deterministic candidate-bound semantic probes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
BINDING_PATHS = {
    "skill": "SKILL.md",
    "runtime": "scripts/identity_label_case.py",
    "test_manifest": "evals/test-generation-manifest.json",
    "policy_rules": "references/policy-rules.md",
}
STRATEGIES = ("lexical_variant", "scope_collision", "nonpersonal_control")


class DiscoveryError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DiscoveryError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise DiscoveryError(f"expected object: {path}")
    return value


def registered_test_corpus(root: Path) -> str:
    manifest = read_object(root / BINDING_PATHS["test_manifest"])
    records = manifest.get("files")
    if not isinstance(records, list):
        raise DiscoveryError("invalid test manifest files")
    texts: list[str] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise DiscoveryError("invalid test manifest record")
        relative = record["path"]
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise DiscoveryError("unsafe registered test path")
        path = root / candidate
        if not path.is_file() or path.is_symlink() or sha256(path) != record.get("sha256"):
            raise DiscoveryError(f"registered test drift: {relative}")
        texts.append(path.read_text(encoding="utf-8"))
    return "\n".join(texts)


def generated_probe(
    strategy: str,
    index: int,
    rng: random.Random,
) -> tuple[str, list[str]]:
    labels = ["慢热型", "回避型", "典型 I 人", "低能量体质", "拖延症人格"]
    decisions = ["主持跨部门会议", "维护半年项目", "在复盘会上公开表达", "承担一次协调任务"]
    label = labels[rng.randrange(len(labels))]
    decision = decisions[rng.randrange(len(decisions))]
    nonce = f"〔探针{index + 1:02d}〕"
    if strategy == "lexical_variant":
        openings = [
            "某个聊天机器人只看了三句对话，就断言",
            "我把一次卡住概括成",
            "一份非正式网络测试把我写成",
        ]
        text = (
            f"{nonce}{openings[rng.randrange(len(openings))]}“{label}”，"
            f"所以我肯定永远做不好{decision}。"
        )
        return text, ["route:deconstruct", "trigger:true", "judgments:present"]
    if strategy == "scope_collision":
        variants = [
            f"朋友说：‘我被另一个 AI 叫作{label}，所以一定做不好{decision}。’这是他的原话，不是我的情况。",
            f"我不是在自称{label}；请只核对另一个 AI 的句子：‘你是{label}，所以无法{decision}。’",
            f"文章里的受访者被写成{label}并被断定不能{decision}，请别把这当成我的经历。",
        ]
        return nonce + variants[rng.randrange(len(variants))], [
            "route:needs_information",
            "trigger:false",
            "labels:none",
        ]
    variants = [
        f"请解释社交媒体上“{label}”通常指什么；这不是对我的描述，也不要替我判断人格。",
        f"请审查广告文案‘{label}的人注定不能{decision}’，只分析文案，不分析我。",
        f"我在整理术语表：{label}和行为描述有什么区别？没有提供任何个人案例。",
    ]
    return nonce + variants[rng.randrange(len(variants))], [
        "route:needs_information",
        "trigger:false",
        "labels:none",
    ]


def normalized_probe_body(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    without_nonce = re.sub(r"^〔探针\d+〕", "", normalized, count=1)
    return re.sub(r"\s+", "", without_nonce).strip()


def observed_signals(case: dict) -> list[str]:
    route = case.get("route") if isinstance(case.get("route"), dict) else {}
    analysis = case.get("analysis") if isinstance(case.get("analysis"), dict) else {}
    risk = case.get("risk_flags") if isinstance(case.get("risk_flags"), dict) else {}
    labels = analysis.get("labels") if isinstance(analysis.get("labels"), list) else []
    judgments = (
        analysis.get("judgments") if isinstance(analysis.get("judgments"), list) else []
    )
    signals = {
        f"route:{route.get('mode', 'missing')}",
        f"trigger:{str(route.get('trigger')).lower()}",
        "labels:present" if labels else "labels:none",
        "judgments:present" if judgments else "judgments:none",
        f"clinical:{str(risk.get('clinical')).lower()}",
        f"functional_impairment:{str(risk.get('functional_impairment')).lower()}",
    }
    for label in labels:
        if isinstance(label, dict) and isinstance(label.get("source"), str):
            signals.add(f"source:{label['source']}")
    return sorted(signals)


def run_probe(root: Path, text: str) -> tuple[list[str], str | None]:
    runtime = root / BINDING_PATHS["runtime"]
    completed = subprocess.run(
        [
            sys.executable,
            str(runtime),
            "scaffold",
            "--text",
            text,
            "--clock",
            "2026-08-07T00:00:00Z",
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        env={"PYTHONHASHSEED": "0"},
    )
    if completed.returncode != 0:
        return [f"runtime_exit:{completed.returncode}"], "runtime_failed"
    try:
        case = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ["runtime_output:invalid_json"], "invalid_json"
    if not isinstance(case, dict):
        return ["runtime_output:not_object"], "not_object"
    return observed_signals(case), None


def build_report(root: Path, seed: str, minimum_probes: int) -> dict:
    root = root.expanduser().resolve()
    if minimum_probes < 6:
        raise DiscoveryError("minimum probes must be at least 6")
    for relative in BINDING_PATHS.values():
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise DiscoveryError(f"missing candidate binding: {relative}")
    corpus = registered_test_corpus(root)
    rng = random.Random(seed)
    probes: list[dict] = []
    seen_bodies: dict[str, set[str]] = {strategy: set() for strategy in STRATEGIES}
    for index in range(minimum_probes):
        strategy = STRATEGIES[index % len(STRATEGIES)]
        collision_round = 0
        while True:
            text, expected = generated_probe(strategy, index, rng)
            body = normalized_probe_body(text)
            if text not in corpus and body not in seen_bodies[strategy]:
                break
            collision_round += 1
            if collision_round >= 256:
                text += f"〔确定性变体{collision_round}〕"
                body = normalized_probe_body(text)
                if text not in corpus and body not in seen_bodies[strategy]:
                    break
        seen_bodies[strategy].add(body)
        observed, runtime_error = run_probe(root, text)
        missing = sorted(set(expected) - set(observed))
        if runtime_error is not None:
            missing.append(runtime_error)
        probes.append(
            {
                "probe_id": f"D{index + 1:03d}",
                "strategy": strategy,
                "input": text,
                "expected_signals": expected,
                "observed_signals": observed,
                "status": "pass" if not missing else "blindspot",
                "missing_signals": sorted(set(missing)),
            }
        )
    blindspots = sum(item["status"] == "blindspot" for item in probes)
    return {
        "schema_version": "1.0",
        "run_type": "deterministic_blindspot_discovery",
        "seed": seed,
        "candidate_bindings": {
            name: {"path": relative, "sha256": sha256(root / relative)}
            for name, relative in BINDING_PATHS.items()
        },
        "strategy_inventory": list(STRATEGIES),
        "probes": probes,
        "summary": {
            "probe_count": len(probes),
            "pass_count": len(probes) - blindspots,
            "blindspot_count": blindspots,
        },
    }


def write_new_json(path: Path, payload: dict) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
    ) as handle:
        staging = Path(handle.name)
        handle.write(encoded)
        handle.flush()
    try:
        if path.exists():
            raise DiscoveryError(f"output already exists: {path}")
        # Hard-link publication gives create-only behavior on the same volume.
        os.link(staging, path)
    finally:
        if staging.exists():
            staging.unlink()


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    value.add_argument("--seed", required=True)
    value.add_argument("--minimum-probes", type=int, default=9)
    value.add_argument("--output", required=True, type=Path)
    value.add_argument("--fail-on-blindspot", action="store_true")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        report = build_report(args.root, args.seed, args.minimum_probes)
        write_new_json(args.output, report)
    except DiscoveryError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    if args.fail_on_blindspot and report["summary"]["blindspot_count"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
