# RC.5 host-model retest environment

- Attempt date: 2026-08-05
- Runner: OpenAI Codex CLI 0.132.0
- Requested model: `gpt-5.5`
- Sandbox: `read-only`
- Requested isolation: one fresh `--ephemeral` process per case
- User config: `--ignore-user-config`
- Host: macOS 26.5.2, build 25F84, arm64
- Python: CPython 3.14.4
- Inputs: the unchanged four files under `evals/retest/raw/`

All four processes stopped before a model response because the CLI account usage gate returned exit `1`:

```text
ERROR: You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at Aug 12th, 2026 6:13 PM.
```

No final response file was produced for any case. Therefore RC.5 has no host-model score. The error is an external runner limit, not a Skill PASS or a semantic FAIL.

## Frozen RC.5 hashes

| Artifact | SHA-256 |
|---|---|
| `SKILL.md` | `efb63381cd345d8cbececf6dc116663e69329f46237a7a606b3e86190097d5c1` |
| `scripts/dpbp` | `4d9f8d2de5b057cf3a5d3d859448d8a074efab4049f7ec3a004111e9371b3481` |
| `runtime/routes.json` | `b085bcc3d25d01a8dc5a3266435fe4419af6ee84c91f1074d6d64874b6dd416c` |
| `schemas/request-envelope.schema.json` | `952f37482c74b0167b04f32a01d08af5c596ad4d3d68e420bae55a9405bd2f88` |
| `schemas/problem-spec.schema.json` | `caf481198d15e906cf04d85faa8d619ab3afc275b77db3ea745fbd79d287de4f` |
| `schemas/problem-state.schema.json` | `49600620835d621e2b87aad2d16b7c9a0173f515ab276950932e4d3f5d67de89` |
| `VERSION` | `75539262603cedf4afafa8d1b8feb2e37377cbfa014e00f14a3c8c0bf94a82b0` |

The RC.5 hashes above are this round's frozen authoritative artifact record. The mutable `evals/runtime/results.json` has since advanced to RC.6 and must not be cited as an RC.5 machine-eval record.
