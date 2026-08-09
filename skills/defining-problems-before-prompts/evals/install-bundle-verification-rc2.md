# Lean bundle verification for 0.3.0-rc.2

Date: 2026-08-06  
Scope: reproducible staging bundle only. This is not proof that a target host discovered or invoked the Skill.

## Environment

- macOS 26.5.2, build 25F84, arm64
- CPython 3.14.4
- `uv 0.11.2`
- OpenAI `skill-creator` quick validator with offline PyYAML environment

## Commands exercised

```bash
python3 scripts/package_skill.py --target-root <empty-root-one>
python3 scripts/package_skill.py --target-root <empty-root-two>
uv run --offline --with pyyaml python <skill-creator>/scripts/quick_validate.py <bundle>
<bundle>/scripts/dpbp doctor
<bundle>/scripts/dpbp version
```

## Results

| Check | Result |
|---|---|
| Explicit allowlist build one | PASS |
| Explicit allowlist build two | PASS |
| Source allowlist tree SHA-256 | `d2f2deac088e715965999bbf309aa49788168ef43cad961d3691b0fcc685b4e3` |
| Target tree SHA-256, both builds | `d2f2deac088e715965999bbf309aa49788168ef43cad961d3691b0fcc685b4e3` |
| Two independently staged bundle roots byte-equal | PASS |
| Official quick validator | `Skill is valid!` |
| Bundled `doctor` | 15/15 |
| Bundled version | `0.3.0-rc.2` |
| Absolute macOS home-prefix, Vault name and session/thread identifier scan in bundle | no matches |

The packaging regression suite separately proves that a symlinked allowlisted leaf or any symlinked ancestor fails closed. Tests, historical transcripts, maintainer evolution tooling, demo and launch notes remain outside this bundle.

## Distribution boundary

The candidate repository as a whole is not the release artifact. It contains other components, private-workflow metadata and historical evaluation records that require separate privacy and rights review. Only the `install-manifest.json` allowlist was checked by this record.

No bundle was copied into a live host Skill directory. Host discovery, negative discovery and current-model behavior remain untested for this version.
