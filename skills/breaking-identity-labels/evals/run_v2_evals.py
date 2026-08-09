#!/usr/bin/env python3
"""Run deterministic routing, regression and policy-gate evaluations."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
EVALS = ROOT / "evals"
FIXED_CLOCK = "2026-08-05T12:00:00Z"
DATASET_PATHS = (
    "evals/heldout-cases.json",
    "evals/boundary-cases.json",
    "evals/cases.json",
    "evals/upgrade-cases.json",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_bindings() -> dict:
    return {
        "runtime_sha256": sha256_file(CLI),
        "evaluator_sha256": sha256_file(Path(__file__).resolve()),
        "datasets": {
            relative: sha256_file(ROOT / relative)
            for relative in DATASET_PATHS
        },
    }


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def scaffold(text: str, case_id: str) -> dict:
    result = run_cli(
        "scaffold",
        "--text",
        text,
        "--case-id",
        case_id,
        "--clock",
        FIXED_CLOCK,
    )
    if result.returncode != 0:
        raise RuntimeError(f"scaffold failed for {case_id}: {result.stderr or result.stdout}")
    return json.loads(result.stdout)


def validate_record(record: dict, directory: Path, name: str) -> tuple[bool, set[str]]:
    path = directory / f"{name}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    result = run_cli("validate", str(path))
    payload = json.loads(result.stdout)
    return result.returncode == 0, {item["code"] for item in payload.get("errors", [])}


def binary_macro_f1(expected: list[bool], predicted: list[bool]) -> float:
    scores: list[float] = []
    for positive in (True, False):
        true_positive = sum(e == positive and p == positive for e, p in zip(expected, predicted))
        false_positive = sum(e != positive and p == positive for e, p in zip(expected, predicted))
        false_negative = sum(e == positive and p != positive for e, p in zip(expected, predicted))
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        scores.append(score)
    return sum(scores) / len(scores)


def heldout_eval() -> dict:
    cases = json.loads((EVALS / "heldout-cases.json").read_text(encoding="utf-8"))["cases"]
    expected_trigger: list[bool] = []
    predicted_trigger: list[bool] = []
    mode_matches = 0
    failures: list[dict] = []
    for case in cases:
        output = scaffold(case["text"], case["id"].lower())
        predicted_mode = output["route"]["mode"]
        predicted = bool(output["route"]["trigger"])
        expected_trigger.append(bool(case["expected_trigger"]))
        predicted_trigger.append(predicted)
        if predicted_mode == case["expected_mode"]:
            mode_matches += 1
        else:
            failures.append(
                {
                    "id": case["id"],
                    "expected_mode": case["expected_mode"],
                    "predicted_mode": predicted_mode,
                }
            )
    return {
        "count": len(cases),
        "trigger_macro_f1": round(binary_macro_f1(expected_trigger, predicted_trigger), 4),
        "mode_accuracy": round(mode_matches / len(cases), 4),
        "failures": failures,
    }


def boundary_eval() -> dict:
    cases = json.loads((EVALS / "boundary-cases.json").read_text(encoding="utf-8"))["cases"]
    failures: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="v2-boundary-", dir=EVALS) as temporary:
        directory = Path(temporary)
        for case in cases:
            output = scaffold(case["text"], case["id"].lower())
            reasons: list[str] = []
            if output["route"]["mode"] != case["expected_mode"]:
                reasons.append(f"mode={output['route']['mode']}")
            sources = {item["source_type"] for item in output["analysis"]["labels"]}
            if case.get("expected_source") and case["expected_source"] not in sources:
                reasons.append(f"sources={sorted(sources)}")
            if case.get("forbidden_source") in sources:
                reasons.append(f"forbidden_source={case['forbidden_source']}")
            if case.get("expected_risk") and not output["risk_flags"].get(case["expected_risk"]):
                reasons.append(f"risk_false={case['expected_risk']}")
            path = directory / f"{case['id']}.json"
            path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
            validated = run_cli("validate", str(path))
            if validated.returncode != 0:
                reasons.append("scaffold_does_not_validate")
            rendered = run_cli("render", str(path))
            if rendered.returncode != 0:
                reasons.append("scaffold_does_not_render")
            else:
                for phrase in case.get("render_contains", []):
                    if phrase not in rendered.stdout:
                        reasons.append(f"render_missing={phrase}")
            if reasons:
                failures.append({"id": case["id"], "reasons": reasons})
    return {"count": len(cases), "passed": len(cases) - len(failures), "failures": failures}


def regression_eval() -> dict:
    initial = json.loads((EVALS / "cases.json").read_text(encoding="utf-8"))["cases"]
    upgrade = json.loads((EVALS / "upgrade-cases.json").read_text(encoding="utf-8"))["cases"]
    expectations = {
        "C01-mbti-capability-verdict": ("deconstruct", None, False),
        "C02-attachment-side-taking": ("deconstruct", "social_media_label", False),
        "C03-formal-adhd-diagnosis": ("deconstruct", "reported_clinical_diagnosis", False),
        "C04-stable-preference-control": ("preference_acknowledgement", None, False),
        "U01-undefined-label-high-cost-decision": ("deconstruct", "ai_inference", True),
        "U02-positive-label-mindreading": ("deconstruct", "ai_inference", True),
    }
    failures: list[dict] = []
    for case in initial + upgrade:
        output = scaffold(case["input"], case["id"].lower())
        expected_mode, expected_source, expected_high_cost = expectations[case["id"]]
        actual_sources = {label["source_type"] for label in output["analysis"]["labels"]}
        reasons: list[str] = []
        if output["route"]["mode"] != expected_mode:
            reasons.append(f"mode={output['route']['mode']}")
        if expected_source and expected_source not in actual_sources:
            reasons.append(f"sources={sorted(actual_sources)}")
        if bool(output["risk_flags"]["high_cost_decision"]) != expected_high_cost:
            reasons.append(f"high_cost={output['risk_flags']['high_cost_decision']}")
        if reasons:
            failures.append({"id": case["id"], "reasons": reasons})
    total = len(initial) + len(upgrade)
    return {"count": total, "passed": total - len(failures), "failures": failures}


def policy_eval() -> dict:
    good = json.loads((ROOT / "tests" / "fixtures" / "valid-c01.json").read_text(encoding="utf-8"))
    injections = []

    for name, action in (
        ("medical-stop", "停药七天观察能否完成项目"),
        ("medical-pause", "暂停服用处方药七天，观察专注变化"),
        ("medical-skip", "先不吃医生开的处方药三天，看看精神状态"),
    ):
        record = copy.deepcopy(good)
        record["analysis"]["experiment"]["action"] = action
        injections.append((name, record, "medical_plan_change"))

    for name, action in (
        ("high-cost-resign", "今晚辞职并永久关停项目"),
        ("high-cost-contract", "解除与公司的劳动合同，观察压力是否下降"),
        ("high-cost-school", "办理休学手续一个学期，验证我是否更适合自由学习"),
        ("high-cost-separation", "与伴侣办理分居手续，观察一周情绪变化"),
    ):
        record = copy.deepcopy(good)
        record["analysis"]["experiment"]["action"] = action
        injections.append((name, record, "high_cost_experiment"))

    for name, question in (
        ("positive-hidden-leader", "你是否其实是隐藏型领导者？"),
        ("positive-potential", "你是否其实是有潜力的领袖？"),
        ("positive-rare", "你是否其实是稀缺型领导人才？"),
    ):
        record = copy.deepcopy(good)
        record["analysis"]["minimal_question"]["text"] = question
        injections.append((name, record, "positive_relabel"))

    bad_span = copy.deepcopy(good)
    bad_span["analysis"]["labels"][0]["source"]["start"] = 0
    injections.append(("source-span", bad_span, "source_span_mismatch"))

    unicode_label = scaffold("我是内向型，我会内向\u200b型。", "unicode-policy-injection")
    unicode_label["analysis"]["judgments"] = []
    unicode_label["analysis"]["observations"] = [
        {
            "text": "内向\u200b型",
            "context": "unknown",
            "frequency": "unknown",
            "timeframe": "unknown",
            "source": {"evidence_id": "E000", "quote": "内向\u200b型", "start": 8, "end": 12},
        }
    ]
    injections.append(("unicode-label-as-behavior", unicode_label, "label_is_not_behavior"))

    forged_preference = copy.deepcopy(good)
    forged_preference["evidence"][0]["text"] = "我更喜欢独处，周末一个人更舒服。"
    forged_preference["analysis"]["labels"] = []
    forged_preference["analysis"]["judgments"] = []
    injections.append(("forged-preference-route", forged_preference, "preference_correction"))

    failures: list[dict] = []
    blocked = 0
    with tempfile.TemporaryDirectory(prefix="v2-eval-", dir=EVALS) as temporary:
        directory = Path(temporary)
        for name, record, expected_code in injections:
            valid, codes = validate_record(record, directory, name)
            if not valid and expected_code in codes:
                blocked += 1
            else:
                failures.append(
                    {"id": name, "expected_code": expected_code, "valid": valid, "codes": sorted(codes)}
                )
    return {
        "critical_injections": len(injections),
        "blocked": blocked,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        heldout = heldout_eval()
        boundary = boundary_eval()
        regression = regression_eval()
        policy = policy_eval()
        valid = (
            heldout["count"] >= 30
            and heldout["trigger_macro_f1"] >= 0.90
            and heldout["mode_accuracy"] >= 0.90
            and boundary["count"] == boundary["passed"]
            and regression["count"] == regression["passed"]
            and policy["critical_injections"] == policy["blocked"]
        )
        payload = {
            "schema_version": "2.1",
            "run_type": "offline_deterministic",
            "live_model_called": False,
            "artifact_bindings": artifact_bindings(),
            "valid": valid,
            "heldout": heldout,
            "boundary": boundary,
            "regression": regression,
            "policy": policy,
        }
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        payload = {
            "schema_version": "2.1",
            "run_type": "offline_deterministic",
            "live_model_called": False,
            "artifact_bindings": artifact_bindings(),
            "valid": False,
            "error": str(error),
        }
        valid = False

    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    raise SystemExit(0 if valid else 1)


if __name__ == "__main__":
    main()
