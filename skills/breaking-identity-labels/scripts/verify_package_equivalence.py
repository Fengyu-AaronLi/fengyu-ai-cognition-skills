#!/usr/bin/env python3
"""Prove directory, archive and installed Skill copies share one byte tree."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from build_package import PackageError, verify_package


def verify(directory: Path, archive: Path, installed: Path) -> dict:
    results = {
        "directory": verify_package(directory),
        "archive": verify_package(archive),
        "installed": verify_package(installed),
    }
    digests = {name: result.get("tree_sha256") for name, result in results.items()}
    manifest_digests = {
        name: result.get("manifest_sha256") for name, result in results.items()
    }
    if (
        any(not isinstance(value, str) or len(value) != 64 for value in digests.values())
        or len(set(digests.values())) != 1
    ):
        raise PackageError("package tree digests are not identical")
    if (
        any(
            not isinstance(value, str) or len(value) != 64
            for value in manifest_digests.values()
        )
        or len(set(manifest_digests.values())) != 1
    ):
        raise PackageError("package manifest digests are not identical")
    tree_sha256 = next(iter(digests.values()))
    manifest_sha256 = next(iter(manifest_digests.values()))
    return {
        "schema_version": "1.0",
        "valid": True,
        "manifest_sha256": manifest_sha256,
        "tree_sha256": tree_sha256,
        "forms": {
            name: {
                "package": result["package"],
                "manifest_sha256": result["manifest_sha256"],
                "tree_sha256": result["tree_sha256"],
            }
            for name, result in results.items()
        },
        "distribution_status": "local_unpublished",
        "publication_actions_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--installed", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.directory, args.archive, args.installed)
    except (OSError, PackageError, zipfile.BadZipFile) as error:
        print(
            json.dumps(
                {"schema_version": "1.0", "valid": False, "errors": [str(error)]},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
