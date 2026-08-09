# Lean bundle verification for 0.3.0-rc.3

Date: 2026-08-06  
Scope: reproducible staging bundle only. This is not proof that a target host discovered or invoked the Skill.

## Environment

- macOS 26.5.2, build 25F84, arm64
- CPython 3.14.4
- `uv 0.11.2`
- OpenAI `skill-creator` quick validator with offline PyYAML environment

## Commands exercised

```bash
python3 scripts/package_skill.py --target-root <empty-root-a>
python3 scripts/package_skill.py --target-root <empty-root-b>
uv run --offline --with pyyaml python <skill-creator>/scripts/quick_validate.py <bundle>
<bundle>/scripts/dpbp doctor
<bundle>/scripts/dpbp version
```

## Results

| Check | Result |
|---|---|
| Explicit allowlist build A | PASS |
| Explicit allowlist build B | PASS |
| Source allowlist tree SHA-256 | `e2c3de65ec386085a16d542f1d3924f55fd1d82f79687cc1bb946aeb28ae2810` |
| Target tree SHA-256, both builds | `e2c3de65ec386085a16d542f1d3924f55fd1d82f79687cc1bb946aeb28ae2810` |
| Two independently staged bundle roots byte-equal | PASS |
| Official quick validator | `Skill is valid!` |
| Bundled `doctor` | 15/15 |
| Bundled version | `0.3.0-rc.3` |
| Absolute macOS home-prefix, Vault name and session/thread identifier scan in bundle | no matches |

The packaging regression suite separately proves that a symlinked allowlisted leaf or any symlinked ancestor fails closed. Tests, historical transcripts, maintainer evolution tooling, demo and launch notes remain outside this bundle.

## Distribution boundary

The candidate repository as a whole is not the release artifact. It contains other components, private-workflow metadata and historical evaluation records that require separate privacy and rights review. Only the `install-manifest.json` allowlist was checked by this record.

No bundle was copied into a live host Skill directory. Host discovery, negative discovery and current-model behavior remain untested for this version.
