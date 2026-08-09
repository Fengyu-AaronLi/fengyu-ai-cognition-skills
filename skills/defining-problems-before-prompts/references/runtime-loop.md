# Evidence Loop Contract

Use this reference only after a validated `define` or `defer_to_user` spec genuinely needs another turn. Clear tasks never enter the loop.

## State flow

```text
awaiting_answers
  -> resume(answer)
  -> needs_reassessment
  -> advance(revised spec)
     -> awaiting_answers        unresolved and budget remains
     -> needs_reassessment      unresolved, no question scheduled, host must revise or run the evidence test
     -> ready_for_answer        problem is defined
     -> awaiting_user_decision  facts are defined but the value choice is user-owned
     -> budget_exhausted        max_rounds reached
```

`user_decision_recorded` is terminal only after every listed value tradeoff has one unique fresh decision. If one of several tradeoffs is covered, the state remains `awaiting_user_decision` and still allows `decide`. `ready_for_answer` and `budget_exhausted` are also terminal. Terminal states reject new answers instead of drifting into endless clarification.

## Commands and payloads

Start with a validated provisional spec:

```bash
scripts/dpbp start --state /explicit/state.json --max-rounds 3 < problem-spec.json
```

Record one answer to a pending question:

```json
{"answer_id":"a1","question_id":"q1","answer":"用户原话","expected_revision":1}
```

The runtime creates evidence source `answer:a1`. A revised claim may cite it with:

```json
{"source_id":"answer:a1","start":0,"end":4,"quote":"用户原话"}
```

After the current questions are answered, submit a fully revised spec:

```json
{"advance_id":"advance-1","expected_revision":4,"spec":{"...":"完整 Problem Spec"}}
```

`confirmed` is accepted only through state-aware `advance`. The desired outcome and each success criterion must quote active post-start `answer:` or `amendment:` evidence; original-request-only support, superseded evidence and model-invented string criteria cannot certify convergence. Decisive unknowns and questions must be empty, and each criterion must add an observable dimension rather than wrap the same goal in “record whether” or “acceptance.” A provisional spec may still propose string criteria for the user to confirm. Standalone `validate` rejects an unsupported `confirmed` claim.

Inspect without writing:

```bash
scripts/dpbp status --state /explicit/state.json
```

Correct an answer without deleting history:

```json
{"amendment_id":"m1","answer_id":"a1","answer":"修订后的用户原话","expected_revision":2}
```

The old answer and source become `superseded`; `amendment:m1` becomes active. Evidence cannot cite a superseded source.

For `defer_to_user`, the runtime stops at `awaiting_user_decision`. The final choice must arrive as a fresh user input after that stop. Earlier answers gathered to define the problem cannot be recycled as the decision. `selection` must equal an exact span in `user_input`, under source ID `decision_input:<decision_id>`, and that span must express a committed choice. A decision marker elsewhere, “I cannot decide,” an undecided phrase or a question cannot form the terminal event:

```json
{"decision_id":"d1","actor":"user","tradeoff_id":"t1","selection":"我选择留下并先谈条件。","user_input":"我选择留下并先谈条件。","source":{"source_id":"decision_input:d1","start":0,"end":11,"quote":"我选择留下并先谈条件。"},"expected_revision":5}
```

When `value_tradeoffs` contains `t1 ... tn`, submit a separate fresh decision for each ID. A new `decision_id` cannot overwrite or duplicate an already-covered tradeoff. Exact replay of the original decision event remains idempotent. Only complete tradeoff coverage reaches `user_decision_recorded`.

## Guarantees and limits

- Atomic writes, local file locking, revision compare-and-swap, and event-id replay protect state integrity.
- The evidence log retains original, answer, amendment, and fresh decision-input hashes.
- `max_rounds` is 1 to 10; the recommended default is 3.
- The state runtime uses POSIX `fcntl` and is supported on macOS and Linux, not native Windows.
- Do not store sensitive answers unless persistence is necessary and the user has authorized the local workflow.
- Mutation commands return state JSON on stdout. Treat terminal capture and logs as sensitive whenever answers are sensitive.
- `actor=user` plus a decision-bearing `decision_input` span proves local text provenance, not authenticated human identity or complete semantic relevance to the named tradeoff. The host must enforce both boundaries.
