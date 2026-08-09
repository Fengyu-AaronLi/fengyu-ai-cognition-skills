# Lean bundle verification for 0.3.0-rc.4

Date: 2026-08-06  
Scope: reproducible staging bundle only. This is not proof that a target host discovered or invoked the Skill.

## Environment

- macOS 26.5.2, build 25F84, arm64
- CPython 3.14.4
- `uv 0.11.2`
- OpenAI `skill-creator` quick validator with offline PyYAML environment

## Results

| Check | Result |
|---|---|
| Explicit allowlist final builds G and H | PASS |
| Source allowlist tree SHA-256 | `00d1600f012375c7e32d5373b776ec6a9184f4650fec13618d24e9bf9d6c648d` |
| Target tree SHA-256, both builds | `00d1600f012375c7e32d5373b776ec6a9184f4650fec13618d24e9bf9d6c648d` |
| Two independently staged bundle roots byte-equal | PASS |
| Bundle regular files / symlinks | 18 / 0 |
| Source and bundle official quick validator | `Skill is valid!` |
| Bundled `doctor` | 15/15 |
| Bundled version | `0.3.0-rc.4` |
| Absolute macOS home-prefix, Vault name and session/thread identifier scan in bundle | no matches |

The packaging regression suite separately proves that a symlinked allowlisted leaf or source ancestor fails closed. These final builds were made after the independent tail-audit status was written into the included provenance file; earlier RC.4 bundle hashes are stale. Tests, historical transcripts, maintainer evolution tooling, demo and launch notes remain outside this bundle.

## Distribution boundary

The candidate repository as a whole is not the release artifact. It contains other components, private-workflow metadata and historical evaluation records that require separate privacy and rights review. The full Skill source tree also retains four historical Codex session IDs. Only the `install-manifest.json` allowlist was checked by this record.

No bundle was copied into a live host Skill directory. Host discovery, negative discovery and current-model behavior remain untested for this version.
