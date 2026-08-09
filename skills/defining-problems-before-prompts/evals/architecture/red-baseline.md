# Architecture RED baseline

Date: 2026-08-05

This baseline was run against the 0.1 candidate before any runtime, schema, reference or automated test asset existed. It measures whether the package had capability beyond loading a policy prompt. It does not rescore the four behavioral transcripts.

## Frozen pre-upgrade inventory

- `SKILL.md`: 241 lines, 18,598 bytes.
- Skill SHA-256: `5b1b21b933a9f53ef451f21203a1edd0b1869d6960d2a55dc81d7ae99e270cc4`.
- Package: 51 files and 3,026 lines.
- Static model outputs: 28.
- Executable scripts: 0.
- JSON Schemas: 0.
- Automated tests: 0.
- State or recovery protocol: none.

## Environment

- OS: macOS 26.5.2, Darwin 25.5.0 arm64.
- Python: 3.14.4.
- Network or model API: not used.
- Working directory: the Skill root in the local candidate repository.

## Command

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Raw outcome

- Exit code: `1`.
- Tests run: 12.
- Passed: 0.
- Failed: 12.
- Final line: `FAILED (failures=12)`.

Representative raw assertions:

```text
AssertionError: False is not true : scripts/dpbp is missing; current version is prompt-only
AssertionError: 241 not less than or equal to 120 : SKILL.md should dispatch to runtime and references, not carry the whole policy
missing runtime assets: ['scripts/dpbp', 'schemas/request-envelope.schema.json', 'schemas/problem-spec.schema.json', 'schemas/problem-state.schema.json', 'runtime/routes.json', 'references/core.md', 'references/high-risk.md', 'references/field-semantics.md', 'references/playbooks/ai-efficiency.md', 'references/playbooks/ai-product.md', 'adapters/standalone-prompt.md']
```

The absent CLI caused the behavior tests for deterministic gate, validator, renderer, stable errors and resumable state to fail before they could execute.

## Failure conclusion

The 0.1 package had useful ideas, provenance and pressure-tested model behavior. Its 4/4 result was a prompt-behavior eval: a model loaded the full instruction file and produced acceptable transcripts once. The package did not yet have an offline route gate, machine-verifiable Problem Spec, executable red lines, deterministic rendering or recovery state. The user's criticism that it still behaved like a packaged prompt was therefore technically valid.
