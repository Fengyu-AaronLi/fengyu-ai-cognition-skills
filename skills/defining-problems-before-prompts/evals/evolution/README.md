# Failure-driven evolution workflow

`scripts/dpbp-evolve` is maintainer tooling. It is deliberately excluded from the lean install bundle and never edits `SKILL.md` or runtime code. Its job is to decide whether evidence is strong enough to promote a candidate.

## Workflow

1. `init` reads one hash-bound suite manifest. Regression cases are visible; `sealed_holdout` content and paths are not emitted. State and ledger must resolve to distinct filesystem targets.
2. `record` appends a `failure_observed` event with a base RED run receipt. Its `raw_input_sha256` must equal the manifest-bound case input, its actor and failure codes must agree with the event, and the derived state checkpoints that exact receipt's canonical digest. Duplicate event IDs are idempotent only when the payload digest is identical.
3. A human or coding agent creates a candidate outside this tool.
4. `close-cycle` requires the exact base RED receipt recorded by `failure_observed`, a candidate GREEN receipt, a reproduction receipt, reviewer approval, and three distinct declared actor IDs for author, reproducer, and reviewer. All three receipts must bind the same failure input. Reusing a cycle ID is idempotent only when the full close-cycle payload is identical.
5. `promote` marks a GREEN cycle as regression-worthy. For a newly observed case it emits a hash-bound `manifest_proposal`; it never edits the manifest automatically. A maintainer must materialize the fixture, update the suite version, apply the proposal, and rerun the suite.
6. `status` reports budget, holdout state, cycles, and stop reason without exposing sealed input.

Every ledger line contains `sequence`, `previous_hash`, `payload_digest`, `state_sha256`, and `event_hash`. `state_sha256` binds the post-event derived state, so changing only the state file is rejected as `STATE_DERIVATION_MISMATCH`, including during an idempotent-looking repeated `init`. Event IDs are globally unique; internal namespaces are reserved. JSON constants such as NaN and Infinity, non-finite improvements, contradictory pass/fail receipts and namespace collisions fail before mutation. Rewriting or reordering history breaks verification.

## Assurance boundary

`status.assurance` deliberately reports `actor_identity=self_attested` and `run_artifacts=hash_declared`. The runtime verifies receipt shape, manifest input binding, outcome consistency, actor linkage, derived-state checkpoints and distinct actor IDs. It does not authenticate people, prove a runner executed, prove the referenced output bytes still exist, or resist someone who rewrites both state and ledger and recomputes every unkeyed hash. State and ledger are two separate atomic writes, not a cross-file transaction; a process or filesystem failure between them can still require manual recovery. External claims of independent reproduction require a trusted runner, retained artifacts and authenticated reviewer identity outside this local tool. Ledgers created before the `state_sha256` checkpoint contract have no in-place migration path.

## Stop rules

- `iteration_budget_exhausted`: promoted cycles reached `max_iterations`.
- `saturation_reached`: the last configured window of cycles all improved less than `minimum_improvement`.

When either rule fires, new `record`, `close-cycle` and `promote` mutations fail with `EVOLUTION_STOPPED`. A payload already committed before the stop remains exactly replayable and returns its stored result; a changed payload or new event stays blocked. More iterations are not automatically better.

## Minimal command sequence

```bash
scripts/dpbp-evolve init --manifest evals/suite-manifest.json --state /tmp/evolution-state.json --ledger /tmp/evolution-ledger.jsonl
scripts/dpbp-evolve record --state /tmp/evolution-state.json --ledger /tmp/evolution-ledger.jsonl < failure-event.json
scripts/dpbp-evolve close-cycle --state /tmp/evolution-state.json --ledger /tmp/evolution-ledger.jsonl < cycle.json
scripts/dpbp-evolve promote --state /tmp/evolution-state.json --ledger /tmp/evolution-ledger.jsonl < promotion.json
scripts/dpbp-evolve status --state /tmp/evolution-state.json --ledger /tmp/evolution-ledger.jsonl
```

The four original cases are now a public regression partition because repeated development has spent their holdout value. A future sealed holdout must be new, access-controlled, and consumed once.
