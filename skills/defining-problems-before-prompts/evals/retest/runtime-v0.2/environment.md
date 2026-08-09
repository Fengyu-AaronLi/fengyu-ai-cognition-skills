# Runtime v0.2 host-model environment

This run tested the executable 0.2 architecture in four fresh model sessions. It is preserved as a failed semantic regression, not as release evidence.

| Item | Value |
|---|---|
| Date | 2026-08-05 |
| Runner | OpenAI Codex CLI 0.132.0 |
| Model | `gpt-5.5` |
| Sessions | Four fresh `--ephemeral` sessions, one per case |
| Sandbox | read-only |
| Network | The Skill runtime itself is offline; the host agent inherited its normal tool surface |
| OS | macOS 26.5.2, Darwin 25.5.0 arm64 |
| Python | 3.14.4 |
| Skill SHA-256 | `b5c2caaa84b5ff7ae8e61dba0daeb344129603dd79d904a5fc950c91a200750b` |
| Runtime SHA-256 | `ce11bbef96033b84dfff9092055c3e18f2b9b1e27e96e7f8be3e2432c8fd8afb` |

Command shape:

```bash
RUST_LOG=error codex exec --ignore-user-config --ephemeral \
  --skip-git-repo-check -s read-only -m gpt-5.5 --color never \
  -o '<case-output>' -C '../harness' - < '<frozen-case-input>'
```

The harness required the agent to read the candidate `SKILL.md`, use the executable runtime and avoid all expected-result files. During some sessions the CLI reported an incompatible local model-cache field and an unrelated malformed local Skill. All four sessions still exited successfully and wrote final outputs. A successful process exit is not a semantic pass.

