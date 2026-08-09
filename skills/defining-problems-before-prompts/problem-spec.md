# Problem Spec protocol guide

This is a human-readable map. [`schemas/problem-spec.schema.json`](schemas/problem-spec.schema.json) and [`scripts/dpbp`](scripts/dpbp) are co-normative: the schema declares the portable data contract and the runtime enforces cross-field, route and state invariants. A release requires both to agree. Any divergence is a release-blocking defect rather than permission to choose the friendlier interpretation.

## Three artifacts

1. A request envelope records the original request and declared routing signals.
2. The offline gate returns a receipt containing the request identity and hash, domain, route mode, execution permission, route rule and only the references needed for that route.
3. A Problem Spec exists only for `define` and `defer_to_user`. It embeds the unchanged request envelope and gate receipt, and must validate before deterministic rendering.

The gate does not understand a person's true goal. A reasoning model or human proposes the semantic fields; the runtime checks structure, provenance and boundaries.

## Twelve-field mapping

| Rendered section | JSON field | Mechanical rule |
|---|---|---|
| Original question | `original_question` | Must be preserved inside the original request |
| Desired real-world outcome | `desired_outcome` | `stated` needs exact evidence; otherwise `unknown` or labeled hypothesis |
| Possible proxy problem | `proxy_problem` | Inference remains a hypothesis |
| Hidden assumptions | `hidden_assumptions` | Each item is labeled and source-grounded |
| Known facts | `known_facts` | Every fact has an exact source span |
| Decisive unknowns | `decisive_unknowns` | Each item has a stable ID, a typed category and the judgment it changes |
| Hard constraints | `hard_constraints` | Exact source plus constraint type; sunk cost is rejected |
| User-owned tradeoffs | `value_tradeoffs` | Owner is always `user` |
| Success, failure and change evidence | three evidence arrays | Provisional success items may be strings; confirmed items are sourced criteria. Failure and change evidence cannot be omitted |
| Better question | `rewritten_problem` | No silent solution commitment |
| Minimum next test | `next_test` | Evidence collection only, reversible, low cost and stopped before solution commitment |
| High-value questions | `questions` | At most three; each references existing decisive-unknown IDs and states its decision impact |

JSON Schema's `uniqueItems` rejects only whole-object duplicates. The runtime adds a cross-field invariant for `known_facts`: two entries may not have the same case-sensitive `value` after removing leading and trailing whitespace, even when their source spans differ. This runtime rule is part of the co-normative contract and must remain covered by tests.

## Evidence spans

Before state starts, evidence uses zero-based, end-exclusive character offsets into `original_request`; omitted `source_id` means `request`:

```json
{
  "value": "老板要求今天交方案。",
  "source": {
    "start": 14,
    "end": 23,
    "quote": "老板让我今天交方案"
  }
}
```

Inside resumable state, an answer becomes an evidence source such as `answer:a1`; an amendment becomes `amendment:m1`. A claim may include that `source_id`, and the validator checks its span against the active source text. Superseded and unknown source IDs are unavailable. A `confirmed` outcome and every `success_evidence` criterion must cite active `answer:` or `amendment:` sources and preserve its value in the quoted user text; original-request evidence alone cannot certify convergence. The validator also reruns the gate against the embedded request envelope and requires the reproduced receipt, request hash, mode, domain, resources, route rule and execution permission to match the spec. This blocks independent route or receipt field tampering. Because the receipt is self-contained rather than externally signed, a coordinated rewrite of the envelope, receipt and spec still requires an external trust anchor to distinguish it from a new request.

## Unknown coverage and next-test boundary

Every decisive unknown has a stable ID such as `u1`. Questions address those IDs, never category labels. Required domain coverage therefore needs both a concrete unknown in each required category and a question that references its ID.

The next test uses explicit boundary fields: `action_type` must be `evidence_collection`, `evidence_only` must be true and `solution_commitment` must be `none`. These fields reject declared solution design, implementation, decisions and communications. They do not semantically classify every possible free-text paraphrase.

## Evidence loop

Pending questions are derived exactly from the validated spec minus active answer IDs in the current round. Every mutation carries `expected_revision`. `resume` records evidence, `advance` validates the complete revised spec, `amend` supersedes an answer without erasing it, and `status` is read-only. When a high-risk flow reaches `awaiting_user_decision`, `decide` requires `actor=user`, a fresh post-definition `user_input`, and an exact span from the resulting `decision_input:<id>` source. The selected span itself must explicitly express the decision; a decision phrase elsewhere in the input cannot convert a selected background fact into a choice. Earlier diagnostic answers and amendments cannot be recycled as the final choice. This proves text provenance and ordering inside state, not authenticated human identity or complete semantic relevance to the named tradeoff; the host remains responsible for those checks.

`confirmed` is a state convergence claim, not a standalone formatting label. It is rejected outside `advance`, while the outcome remains unknown or low-information, while decisive unknowns remain, while questions are pending, when criteria lack active user confirmation, or when they merely wrap the goal in “record whether” rather than adding a determinate dimension. A provisional spec with no pending questions enters `needs_reassessment` rather than a false `awaiting_answers` state. The loop stops at `ready_for_answer`, `awaiting_user_decision`, or `budget_exhausted`; it cannot clarify forever. Exact payloads and phase transitions are in [`references/runtime-loop.md`](references/runtime-loop.md).

## What runtime validation can and cannot prove

It can mechanically check that required fields exist, unique-item rules hold, sources reproduce the input, receipt fields match the rerun gate, questions stay within the limit, state transitions are well formed and tested prohibited output shapes are absent.

It cannot prove that the chosen desired outcome is what the person truly values, that an author-declared category or action type is truthful, that a proxy diagnosis is insightful, that a tradeoff is complete or that a proposed test will matter in reality. Natural-language pattern checks are not exhaustive semantic proof. Evidence spans prove quotation identity, not correctness or meaning. Local POSIX file locking is not distributed coordination and is not a native Windows contract. Those boundaries remain explicit and must be revised when evidence changes.

## Direct tasks

`execute` produces no Problem Spec. A clear translation or calculation should proceed with zero definition overhead. Trying to attach this schema to an `execute` route is itself a validation failure.
