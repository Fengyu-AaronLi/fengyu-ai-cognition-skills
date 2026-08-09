#!/usr/bin/env python3
"""Build, verify and install a minimal self-contained Skill package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
PACKAGE_NAME = "breaking-identity-labels"
MANIFEST_NAME = "PACKAGE-MANIFEST.json"
MANIFEST_KEYS = {
    "schema_version",
    "package_name",
    "package_version",
    "distribution_status",
    "license",
    "scope",
    "excluded",
    "tree_sha256",
    "files",
}
MANIFEST_FILE_KEYS = {"path", "bytes", "sha256"}
EXCLUDED_ROOTS = ["evals", "examples", "launch", "tests", "workflows"]
MAX_ARCHIVE_MEMBER_BYTES = 5_000_000
MAX_ARCHIVE_TOTAL_BYTES = 20_000_000

PRIVACY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "absolute_home_path",
        re.compile(r"(?:^|[\s\"'=])/(?:Users|home)/[^/\s\"']+/", re.MULTILINE),
    ),
    (
        "windows_user_path",
        re.compile(r"[A-Za-z]:\\Users\\[^\\\s\"']+\\", re.IGNORECASE),
    ),
    (
        "private_key",
        re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    ("openai_style_token", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_style_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)

# Destination path, source path. This allowlist is the distribution boundary.
PACKAGE_FILES: tuple[tuple[str, Path], ...] = (
    ("SKILL.md", ROOT / "SKILL.md"),
    ("VERSION", ROOT / "VERSION"),
    ("SOURCE_OF_TRUTH.md", ROOT / "SOURCE_OF_TRUTH.md"),
    ("README.md", ROOT / "README.md"),
    ("problem-spec.md", ROOT / "problem-spec.md"),
    ("PROVENANCE.md", ROOT / "PROVENANCE.md"),
    ("zero-threshold-prompt.md", ROOT / "zero-threshold-prompt.md"),
    ("LICENSE", ROOT / "LICENSE"),
    ("NOTICE.md", ROOT / "NOTICE.md"),
    ("agents/openai.yaml", ROOT / "agents" / "openai.yaml"),
    ("schemas/analysis.schema.json", ROOT / "schemas" / "analysis.schema.json"),
    ("schemas/case.schema.json", ROOT / "schemas" / "case.schema.json"),
    ("schemas/event-head.schema.json", ROOT / "schemas" / "event-head.schema.json"),
    ("schemas/event.schema.json", ROOT / "schemas" / "event.schema.json"),
    ("schemas/workflow-next.schema.json", ROOT / "schemas" / "workflow-next.schema.json"),
    ("templates/analysis.json", ROOT / "templates" / "analysis.json"),
    ("references/evidence-classes.md", ROOT / "references" / "evidence-classes.md"),
    ("references/policy-rules.md", ROOT / "references" / "policy-rules.md"),
    ("references/safety-boundaries.md", ROOT / "references" / "safety-boundaries.md"),
    ("docs/acceptance.md", ROOT / "docs" / "acceptance.md"),
    ("docs/evolution.md", ROOT / "docs" / "evolution.md"),
    ("docs/quickstart.md", ROOT / "docs" / "quickstart.md"),
    ("scripts/build_package.py", ROOT / "scripts" / "build_package.py"),
    ("scripts/identity_label_case.py", ROOT / "scripts" / "identity_label_case.py"),
)


class PackageError(RuntimeError):
    """A user-visible package boundary failure."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def expected_paths() -> set[str]:
    return {destination for destination, _source in PACKAGE_FILES}


def source_payloads() -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    missing: list[str] = []
    for destination, source in PACKAGE_FILES:
        if not source.is_file():
            missing.append(str(source))
            continue
        payloads[destination] = source.read_bytes()
    if missing:
        raise PackageError("missing source files: " + ", ".join(missing))
    return payloads


def tree_digest(records: Iterable[dict]) -> str:
    normalized = [
        {
            "path": record["path"],
            "bytes": record["bytes"],
            "sha256": record["sha256"],
        }
        for record in sorted(records, key=lambda item: item["path"])
    ]
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256_bytes(payload)


def make_manifest(payloads: dict[str, bytes]) -> dict:
    version = payloads["VERSION"].decode("utf-8").strip()
    records = [
        {
            "path": path,
            "bytes": len(payloads[path]),
            "sha256": sha256_bytes(payloads[path]),
        }
        for path in sorted(payloads)
    ]
    return {
        "schema_version": "1.0",
        "package_name": PACKAGE_NAME,
        "package_version": version,
        "distribution_status": "local_candidate",
        "license": "CC BY-NC 4.0",
        "scope": "runtime_allowlist",
        "excluded": EXCLUDED_ROOTS,
        "tree_sha256": tree_digest(records),
        "files": records,
    }


def materialize_package(destination: Path, payloads: dict[str, bytes]) -> dict:
    for relative, payload in payloads.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    manifest = make_manifest(payloads)
    write_json(destination / MANIFEST_NAME, manifest)
    return manifest


def zip_package(package_dir: Path, archive: Path) -> None:
    if archive.exists():
        raise PackageError(f"archive already exists: {archive}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{PACKAGE_NAME}-",
        suffix=".zip",
        dir=archive.parent,
        delete=False,
    ) as handle:
        staging = Path(handle.name)
    try:
        with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for source in sorted(path for path in package_dir.rglob("*") if path.is_file()):
                relative = source.relative_to(package_dir).as_posix()
                info = zipfile.ZipInfo(
                    filename=f"{PACKAGE_NAME}/{relative}",
                    date_time=(1980, 1, 1, 0, 0, 0),
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                bundle.writestr(info, source.read_bytes())
        staging.replace(archive)
    finally:
        if staging.exists():
            staging.unlink()


def build_package(output: Path, archive: Path | None) -> dict:
    output = output.expanduser().resolve()
    if output.exists():
        raise PackageError(f"output already exists: {output}")
    if archive is not None:
        archive = archive.expanduser().resolve()
        if archive.exists():
            raise PackageError(f"archive already exists: {archive}")

    payloads = source_payloads()
    output.parent.mkdir(parents=True, exist_ok=True)
    stage_root = Path(tempfile.mkdtemp(prefix=f".{PACKAGE_NAME}-", dir=output.parent))
    staged_package = stage_root / PACKAGE_NAME
    try:
        staged_package.mkdir()
        manifest = materialize_package(staged_package, payloads)
        verify_directory(staged_package)
        staged_package.replace(output)
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)

    if archive is not None:
        zip_package(output, archive)
        verify_archive(archive)

    return {
        "status": "built",
        "package": str(output),
        "archive": str(archive) if archive is not None else None,
        "package_version": manifest["package_version"],
        "file_count": len(manifest["files"]),
        "manifest_sha256": sha256_bytes((output / MANIFEST_NAME).read_bytes()),
        "tree_sha256": manifest["tree_sha256"],
    }


def load_manifest(package_dir: Path) -> dict:
    path = package_dir / MANIFEST_NAME
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise PackageError(f"missing {MANIFEST_NAME}") from error
    except json.JSONDecodeError as error:
        raise PackageError(f"invalid {MANIFEST_NAME}: {error}") from error
    if not isinstance(manifest, dict):
        raise PackageError(f"{MANIFEST_NAME} must contain an object")
    return manifest


def package_files(package_dir: Path) -> set[str]:
    symlinks = [
        path.relative_to(package_dir).as_posix()
        for path in package_dir.rglob("*")
        if path.is_symlink()
    ]
    if symlinks:
        raise PackageError("package contains symlinks: " + ", ".join(sorted(symlinks)))
    return {
        path.relative_to(package_dir).as_posix()
        for path in package_dir.rglob("*")
        if path.is_file()
    }


def verify_runtime_smoke(package_dir: Path) -> None:
    runtime = package_dir / "scripts" / "identity_label_case.py"

    def run_stage(
        stage: str,
        command: list[str],
        cwd: Path,
        *,
        require_valid: bool = True,
    ) -> dict:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
            raise PackageError(f"runtime smoke {stage} failed: {detail}")
        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise PackageError(
                f"runtime smoke {stage} did not return valid JSON"
            ) from error
        if not isinstance(response, dict):
            raise PackageError(f"runtime smoke {stage} did not return an object")
        if require_valid and response.get("valid") is not True:
            raise PackageError(f"runtime smoke {stage} did not report valid: true")
        return response

    def load_stage_json(stage: str, artifact: Path) -> dict:
        try:
            value = json.loads(artifact.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PackageError(
                f"runtime smoke {stage} did not materialize valid JSON"
            ) from error
        if not isinstance(value, dict):
            raise PackageError(f"runtime smoke {stage} artifact must contain an object")
        return value

    def snapshot_package_tree() -> dict[str, tuple[str, bytes]]:
        snapshot: dict[str, tuple[str, bytes]] = {}
        for path in sorted(package_dir.rglob("*")):
            relative = path.relative_to(package_dir).as_posix()
            if path.is_symlink():
                snapshot[relative] = ("symlink", os.readlink(path).encode("utf-8"))
            elif path.is_file():
                snapshot[relative] = ("file", path.read_bytes())
            elif path.is_dir():
                snapshot[relative] = ("directory", b"")
        return snapshot

    package_before = snapshot_package_tree()
    with tempfile.TemporaryDirectory(prefix=f"{PACKAGE_NAME}-runtime-smoke-") as temp:
        work = Path(temp)
        user_input = work / "user-input.txt"
        scaffold = work / "scaffold.json"
        analysis = work / "analysis.json"
        case = work / "case.json"
        report = work / "report.md"
        user_input.write_text(
            "我是典型 I 人，所以我不适合带团队，也不可能做好公开表达。",
            encoding="utf-8",
        )

        run_stage(
            "scaffold",
            [
                sys.executable,
                str(runtime),
                "scaffold",
                "--text-file",
                str(user_input),
                "--out",
                str(scaffold),
                "--clock",
                "2026-08-07T00:00:00Z",
            ],
            work,
        )
        scaffold_payload = load_stage_json("scaffold", scaffold)
        if scaffold_payload.get("route", {}).get("mode") != "deconstruct":
            raise PackageError("runtime smoke scaffold returned an unexpected route")
        run_stage(
            "prepare-analysis",
            [
                sys.executable,
                str(runtime),
                "prepare-analysis",
                "--scaffold",
                str(scaffold),
                "--out",
                str(analysis),
            ],
            work,
        )
        analysis_payload = load_stage_json("prepare-analysis", analysis)
        if analysis_payload != scaffold_payload.get("analysis"):
            raise PackageError(
                "runtime smoke prepare-analysis did not preserve the scaffold-bound work order"
            )

        # Simulate the agent's bounded completion of the work order.  The
        # runtime must not invent a planned experiment during prepare-analysis,
        # while compile correctly requires one for a deconstruct route.
        judgment_source = analysis_payload["judgments"][0]["source"]
        target_judgment_id = (
            f"J-{judgment_source['evidence_id']}-"
            f"{judgment_source['start']}-{judgment_source['end']}"
        )
        analysis_payload["candidate_variables"] = [
            {
                "name": "准备时间",
                "status": "hypothesis",
                "reason": "可在相同表达任务中单独调整",
            }
        ]
        analysis_payload["experiment"] = {
            "status": "planned",
            "started_at": None,
            "target_claim": "在有十五分钟准备时，我无法完成三分钟团队更新",
            "target_judgment_ids": [target_judgment_id],
            "primary_variable": "准备时间",
            "duration": {"value": 7, "unit": "days"},
            "action": "完成一次三分钟团队更新",
            "kept_constant": ["表达主题", "听众范围"],
            "measures": ["是否完成", "听众能否复述主要信息"],
            "support_if": ["在固定十五分钟准备后仍未完成团队更新"],
            "weaken_if": ["按时完成更新且听众能够复述主要信息"],
            "reversible": True,
            "reversibility_note": "实验结束后恢复原沟通安排",
        }
        write_json(analysis, analysis_payload)
        run_stage(
            "compile",
            [
                sys.executable,
                str(runtime),
                "compile",
                "--scaffold",
                str(scaffold),
                "--analysis",
                str(analysis),
                "--out",
                str(case),
                "--clock",
                "2026-08-07T00:00:01Z",
            ],
            work,
        )
        case_payload = load_stage_json("compile", case)
        if (
            case_payload.get("status") != "planned"
            or case_payload.get("route") != scaffold_payload.get("route")
            or case_payload.get("analysis") != analysis_payload
        ):
            raise PackageError("runtime smoke compile returned an unexpected planned case")
        validation = run_stage(
            "validate",
            [sys.executable, str(runtime), "validate", str(case)],
            work,
        )
        if validation.get("errors") != []:
            raise PackageError("runtime smoke validate returned unexpected errors")
        run_stage(
            "render",
            [
                sys.executable,
                str(runtime),
                "render",
                str(case),
                "--out",
                str(report),
            ],
            work,
        )
        try:
            rendered = report.read_text(encoding="utf-8")
        except OSError as error:
            raise PackageError("runtime smoke render did not materialize its report") from error
        if "I 人" not in rendered:
            raise PackageError("runtime smoke render lost the source-bound label")

        for stage, artifact in (
            ("scaffold", scaffold),
            ("prepare-analysis", analysis),
            ("compile", case),
            ("render", report),
        ):
            if not artifact.is_file() or artifact.stat().st_size == 0:
                raise PackageError(
                    f"runtime smoke {stage} did not materialize its output artifact"
                )

        case_dir = work / "case-state"
        confirmation = work / "user-confirmation.txt"
        observation = work / "observation.json"
        rationale = work / "rationale.txt"
        confirmation.write_text("我愿意开始这个七天的小实验。", encoding="utf-8")
        write_json(
            observation,
            {
                "source_text": "今天在十五分钟准备后完成了三分钟团队更新，听众能复述两点。",
                "fact": "完成了三分钟团队更新",
                "context": "团队周会",
                "timeframe": "今天",
            },
        )
        rationale.write_text(
            "本次在固定准备时间下完成了目标行为，只能削弱该窄命题。",
            encoding="utf-8",
        )

        initialized = run_stage(
            "init",
            [
                sys.executable,
                str(runtime),
                "init",
                "--text-file",
                str(user_input),
                "--case-dir",
                str(case_dir),
                "--case-id",
                "package-persistent-smoke",
                "--clock",
                "2026-08-07T00:00:00Z",
            ],
            work,
        )
        if initialized.get("case", {}).get("revision") != 0:
            raise PackageError("runtime smoke init returned an unexpected revision")

        planned = run_stage(
            "plan",
            [
                sys.executable,
                str(runtime),
                "plan",
                "--case-dir",
                str(case_dir),
                "--analysis",
                str(analysis),
                "--expected-revision",
                "0",
                "--clock",
                "2026-08-07T00:00:01Z",
            ],
            work,
        )
        if planned.get("case", {}).get("revision") != 1:
            raise PackageError("runtime smoke plan returned an unexpected revision")

        started = run_stage(
            "start",
            [
                sys.executable,
                str(runtime),
                "start",
                "--case-dir",
                str(case_dir),
                "--confirmation-file",
                str(confirmation),
                "--expected-revision",
                "1",
                "--clock",
                "2026-08-07T00:00:02Z",
            ],
            work,
        )
        if started.get("case", {}).get("revision") != 2:
            raise PackageError("runtime smoke start returned an unexpected revision")

        recorded = run_stage(
            "record",
            [
                sys.executable,
                str(runtime),
                "record",
                "--case-dir",
                str(case_dir),
                "--kind",
                "experiment_result",
                "--observation-file",
                str(observation),
                "--operation-id",
                "package-persistent-smoke-001",
                "--expected-revision",
                "2",
                "--clock",
                "2026-08-14T00:00:02Z",
            ],
            work,
        )
        if recorded.get("case", {}).get("revision") != 3:
            raise PackageError("runtime smoke record returned an unexpected revision")

        reviewed = run_stage(
            "review",
            [
                sys.executable,
                str(runtime),
                "review",
                "--case-dir",
                str(case_dir),
                "--classification",
                "weakens",
                "--rationale-file",
                str(rationale),
                "--expected-revision",
                "3",
                "--clock",
                "2026-08-14T00:00:03Z",
            ],
            work,
        )
        reviewed_case = reviewed.get("case", {})
        if reviewed_case.get("status") != "reviewed" or reviewed_case.get("revision") != 4:
            raise PackageError(
                "runtime smoke review did not reach reviewed revision 4"
            )

        replay = run_stage(
            "replay",
            [
                sys.executable,
                str(runtime),
                "replay",
                "--case-dir",
                str(case_dir),
            ],
            work,
        )
        if replay.get("event_count") != 5 or replay.get("latest_revision") != 4:
            raise PackageError(
                "runtime smoke replay requires event_count 5 and latest_revision 4"
            )

        next_step = run_stage(
            "next",
            [
                sys.executable,
                str(runtime),
                "next",
                "--case-dir",
                str(case_dir),
                "--clock",
                "2026-08-14T00:00:04Z",
            ],
            work,
            require_valid=False,
        )
        if (
            next_step.get("complete") is not True
            or next_step.get("stage") != "complete"
            or next_step.get("status") != "reviewed"
            or next_step.get("revision") != 4
        ):
            raise PackageError(
                "runtime smoke next did not report the reviewed terminal complete state"
            )

    package_after = snapshot_package_tree()
    if package_after != package_before:
        raise PackageError(
            "runtime smoke modified the package tree instead of using its external work directory"
        )


def verify_privacy_boundary(package_dir: Path, relatives: Iterable[str]) -> None:
    findings: list[str] = []
    for relative in sorted(relatives):
        payload = (package_dir / relative).read_bytes()
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for rule, pattern in PRIVACY_RULES:
            if pattern.search(text):
                findings.append(f"{relative}:{rule}")
    if findings:
        raise PackageError("privacy boundary violation: " + ", ".join(findings))


def verify_directory(package_dir: Path) -> dict:
    package_dir = package_dir.expanduser().resolve()
    if not package_dir.is_dir():
        raise PackageError(f"package directory does not exist: {package_dir}")

    manifest = load_manifest(package_dir)
    if set(manifest) != MANIFEST_KEYS:
        raise PackageError("manifest top-level schema mismatch")
    if manifest.get("schema_version") != "1.0":
        raise PackageError("manifest schema_version mismatch")
    if manifest.get("package_name") != PACKAGE_NAME:
        raise PackageError("manifest package_name mismatch")
    if manifest.get("distribution_status") != "local_candidate":
        raise PackageError("manifest must preserve local_candidate status")
    if manifest.get("license") != "CC BY-NC 4.0":
        raise PackageError("manifest license mismatch")
    if manifest.get("scope") != "runtime_allowlist":
        raise PackageError("manifest scope mismatch")
    if manifest.get("excluded") != EXCLUDED_ROOTS:
        raise PackageError("manifest excluded roots mismatch")

    declared_items = manifest.get("files")
    if not isinstance(declared_items, list):
        raise PackageError("manifest files must be a list")
    declared: dict[str, dict] = {}
    for item in declared_items:
        if (
            not isinstance(item, dict)
            or set(item) != MANIFEST_FILE_KEYS
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("bytes"), int)
            or isinstance(item.get("bytes"), bool)
            or item["bytes"] < 0
            or not isinstance(item.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None
        ):
            raise PackageError("manifest contains an invalid file record")
        path = item["path"]
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or path in declared:
            raise PackageError(f"manifest contains an unsafe or duplicate path: {path}")
        declared[path] = item

    expected = expected_paths()
    if set(declared) != expected:
        missing = sorted(expected - set(declared))
        extra = sorted(set(declared) - expected)
        raise PackageError(f"manifest allowlist mismatch; missing={missing}, extra={extra}")

    actual = package_files(package_dir)
    expected_actual = expected | {MANIFEST_NAME}
    if actual != expected_actual:
        missing = sorted(expected_actual - actual)
        extra = sorted(actual - expected_actual)
        raise PackageError(f"package boundary mismatch; missing={missing}, extra={extra}")

    for relative, item in declared.items():
        payload = (package_dir / relative).read_bytes()
        if item.get("bytes") != len(payload):
            raise PackageError(f"size mismatch: {relative}")
        if item.get("sha256") != sha256_bytes(payload):
            raise PackageError(f"hash mismatch: {relative}")

    calculated_tree = tree_digest(declared.values())
    if manifest.get("tree_sha256") != calculated_tree:
        raise PackageError("tree digest mismatch")

    version = (package_dir / "VERSION").read_text(encoding="utf-8").strip()
    if manifest.get("package_version") != version:
        raise PackageError("manifest version does not match VERSION")
    if not (package_dir / "SKILL.md").read_text(encoding="utf-8").startswith("---\n"):
        raise PackageError("SKILL.md frontmatter is missing")
    license_text = (package_dir / "LICENSE").read_text(encoding="utf-8")
    if "Attribution-NonCommercial 4.0 International" not in license_text:
        raise PackageError("LICENSE is not the expected CC BY-NC 4.0 text")

    verify_privacy_boundary(package_dir, declared)
    verify_runtime_smoke(package_dir)
    return {
        "valid": True,
        "package": str(package_dir),
        "package_version": version,
        "file_count": len(declared),
        "manifest_sha256": sha256_bytes((package_dir / MANIFEST_NAME).read_bytes()),
        "privacy_scan": "passed",
        "runtime_smoke": "passed",
        "tree_sha256": calculated_tree,
    }


def safe_archive_members(bundle: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = bundle.infolist()
    seen: set[str] = set()
    file_names: set[str] = set()
    total_bytes = 0
    for info in members:
        path = PurePosixPath(info.filename)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or path.parts[0] != PACKAGE_NAME
            or info.filename in seen
        ):
            raise PackageError(f"archive contains an unsafe path: {info.filename}")
        mode = info.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise PackageError(f"archive contains a symlink: {info.filename}")
        if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
            raise PackageError(f"archive size limit exceeded by: {info.filename}")
        total_bytes += info.file_size
        if total_bytes > MAX_ARCHIVE_TOTAL_BYTES:
            raise PackageError("archive size limit exceeded in total")
        if not info.is_dir():
            file_names.add(info.filename)
        seen.add(info.filename)
    expected = {
        f"{PACKAGE_NAME}/{relative}"
        for relative in expected_paths() | {MANIFEST_NAME}
    }
    if file_names != expected:
        missing = sorted(expected - file_names)
        extra = sorted(file_names - expected)
        raise PackageError(f"archive member boundary mismatch; missing={missing}, extra={extra}")
    return members


def verify_archive(archive: Path) -> dict:
    archive = archive.expanduser().resolve()
    if not archive.is_file():
        raise PackageError(f"archive does not exist: {archive}")
    try:
        with tempfile.TemporaryDirectory(prefix=f"{PACKAGE_NAME}-verify-") as temp:
            with zipfile.ZipFile(archive) as bundle:
                safe_archive_members(bundle)
                bundle.extractall(temp)
            result = verify_directory(Path(temp) / PACKAGE_NAME)
    except zipfile.BadZipFile as error:
        raise PackageError(f"invalid zip archive: {archive}") from error
    result["package"] = str(archive)
    result["archive_sha256"] = sha256_bytes(archive.read_bytes())
    return result


def verify_package(path: Path) -> dict:
    return verify_archive(path) if path.suffix.lower() == ".zip" else verify_directory(path)


def package_source(path: Path) -> Iterable[Path]:
    """Yield one verified package directory, extracting an archive when needed."""
    path = path.expanduser().resolve()
    if path.suffix.lower() != ".zip":
        verify_directory(path)
        yield path
        return
    with tempfile.TemporaryDirectory(prefix=f"{PACKAGE_NAME}-install-") as temp:
        with zipfile.ZipFile(path) as bundle:
            safe_archive_members(bundle)
            bundle.extractall(temp)
        extracted = Path(temp) / PACKAGE_NAME
        verify_directory(extracted)
        yield extracted


def install_package(package: Path, skills_dir: Path) -> dict:
    skills_dir = skills_dir.expanduser().resolve()
    destination = skills_dir / PACKAGE_NAME
    if destination.exists():
        raise PackageError(f"skill already exists: {destination}")
    skills_dir.mkdir(parents=True, exist_ok=True)

    for source in package_source(package):
        stage = Path(tempfile.mkdtemp(prefix=f".{PACKAGE_NAME}-", dir=skills_dir))
        try:
            shutil.copytree(source, stage, dirs_exist_ok=True)
            verification = verify_directory(stage)
            if destination.exists():
                raise PackageError(f"skill already exists: {destination}")
            stage.replace(destination)
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    return {
        "status": "installed",
        "installed_at": str(destination),
        "package_version": verification["package_version"],
        "manifest_sha256": verification["manifest_sha256"],
        "tree_sha256": verification["tree_sha256"],
        "overwrite": False,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subparsers = root.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="build an allowlisted local package")
    build.add_argument("--out", required=True, type=Path)
    build.add_argument("--archive", type=Path)

    verify = subparsers.add_parser("verify", help="verify a package directory or zip")
    verify.add_argument("--package", required=True, type=Path)

    install = subparsers.add_parser("install", help="install without overwriting")
    install.add_argument("--package", required=True, type=Path)
    install.add_argument("--skills-dir", required=True, type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_package(args.out, args.archive)
        elif args.command == "verify":
            result = verify_package(args.package)
        else:
            result = install_package(args.package, args.skills_dir)
    except (OSError, PackageError, zipfile.BadZipFile) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
