# RC.4 host-model retest environment

- Date: 2026-08-05
- Runner: OpenAI Codex CLI 0.132.0
- Model: `gpt-5.5`
- Reasoning effort: not explicitly pinned; the refreshed model metadata reported the model default as `medium`
- Sandbox: `read-only`
- Session isolation: one fresh `--ephemeral` session per case
- User config: `--ignore-user-config`
- Working harness: `evals/retest/harness/AGENTS.md`
- Host OS: macOS 26.5.2, build 25F84, arm64
- Python: CPython 3.14.4
- Input policy: the four files under `evals/retest/raw/` were passed unchanged on stdin
- Output policy: `codex exec -o` wrote the final user-facing response for each session directly under `raw/`

The command did not pin reasoning effort, so this run must not be described as an effort=`none` run. During startup, Codex CLI emitted two host warnings: an unrelated local `daliuren` Skill lacked valid frontmatter, and the local model-cache parser did not recognize an unrelated `max` effort entry. The requested `gpt-5.5` sessions nevertheless ran to exit 0 and produced all four output files. These warnings are part of the environment, not evidence that the candidate Skill passed.

## Frozen artifact hashes at execution time

| Artifact | SHA-256 |
|---|---|
| `SKILL.md` | `8836914107ba116c8314e33c9a1c06816bf9cce59f421aa1c27315488b402d54` |
| `scripts/dpbp` | `d476bd5926f975ab32b0a7f65a99f56a9839f4b8d3bdd527604d665b1a5b30e8` |
| `runtime/routes.json` | `b085bcc3d25d01a8dc5a3266435fe4419af6ee84c91f1074d6d64874b6dd416c` |
| `schemas/request-envelope.schema.json` | `9fe07226958cd8f1543e1a459194a9a4d7062c7011abd6c90e934b24476d8348` |
| `schemas/problem-spec.schema.json` | `097e58c96a83a9c475399792fe1051e39744b96b4af6b007e7dd84999ef5e172` |
| `schemas/problem-state.schema.json` | `15320685d7c98faf1db5ef554a693219597f2ae4ac3ace364bb002c82e835f49` |
| `VERSION` | `7bf2def3ff49052bf6a038385a7068ba3e1238afaf4509402a8a2a24e1c0f1ed` |

## Raw output hashes

| Case | SHA-256 |
|---|---|
| DPBP-001 | `dd7c6a6a4a84eb9e3d931ebb4fc7f720b6b60250d496096304a9bc8d6493d211` |
| DPBP-002 | `5d8b7071df579a745bfd3db5b2dba0ea3a63e7089f8d49393dcc6cca3be111e2` |
| DPBP-003 | `c33a0949495218bb267b4cf8277cb45af8fa4ed1076295b3acbc0d17e7e7b4af` |
| DPBP-004 | `f16e9b15635c9045a8866be97bead7750f64798abce8f9f26ad337e5c1fc50ea` |

RC.4 was subsequently blocked by an independent code audit even before the host outputs were given a final release score: the validator did not cryptographically or structurally bind the gate receipt to the Problem Spec, and state consistency plus several semantic boundaries could be bypassed. RC.4 therefore remains preserved failure evidence, not a releasable result.
