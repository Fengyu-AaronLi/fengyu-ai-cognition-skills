# RC.6 host-model retest environment

- Attempt date: 2026-08-06
- Runner: OpenAI Codex CLI 0.132.0
- Requested model: `gpt-5.5`
- Reasoning effort: `none`
- Sandbox: `read-only`
- Requested isolation: one fresh `--ephemeral` process per case
- User config: `--ignore-user-config`
- Host: macOS 26.5.2, build 25F84, arm64
- Python: CPython 3.14.4
- Inputs: the unchanged four files under `evals/retest/raw/`

All four processes created fresh session IDs and printed the requested model, sandbox and input, but stopped before an assistant response. Each returned exit `1` with:

```text
ERROR: You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at Aug 12th, 2026 6:13 PM.
```

The startup log also contained an unrelated Notion connector authentication warning. No candidate Skill output was produced, so neither warning can be used as a PASS or semantic FAIL.

## Session IDs

| Case | Session ID | Exit |
|---|---|---:|
| DPBP-001 | `019fd245-1354-7791-b94a-07f56e515bcb` | 1 |
| DPBP-002 | `019fd245-13db-7952-b4b2-3eb3301679a1` | 1 |
| DPBP-003 | `019fd245-1356-7503-a3e2-cda8c74071f9` | 1 |
| DPBP-004 | `019fd245-1354-77d1-8182-3d84525be2c2` | 1 |

## Frozen RC.6 hashes

| Artifact | SHA-256 |
|---|---|
| `SKILL.md` | `10daf14398262d6b610ab91b65a03ce96a232be35d554694c9d75984b2e4eb43` |
| `scripts/dpbp` | `4d9f8d2de5b057cf3a5d3d859448d8a074efab4049f7ec3a004111e9371b3481` |
| `runtime/routes.json` | `b085bcc3d25d01a8dc5a3266435fe4419af6ee84c91f1074d6d64874b6dd416c` |
| `schemas/request-envelope.schema.json` | `952f37482c74b0167b04f32a01d08af5c596ad4d3d68e420bae55a9405bd2f88` |
| `schemas/problem-spec.schema.json` | `caf481198d15e906cf04d85faa8d619ab3afc275b77db3ea745fbd79d287de4f` |
| `schemas/problem-state.schema.json` | `49600620835d621e2b87aad2d16b7c9a0173f515ab276950932e4d3f5d67de89` |
| `VERSION` | `1a4e7d80fa376bfb18373396bff4ee783b1d8008d34c7884045581d3a514a867` |

The offline runtime report at `evals/runtime/results.json` fingerprints the same RC.6 artifacts.
