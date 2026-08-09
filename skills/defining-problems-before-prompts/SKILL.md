---
name: defining-problems-before-prompts
description: Use when advice, optimization, product design, planning, or a high-stakes choice lacks a real-world outcome, decisive facts, success evidence, or user-owned tradeoffs; not for fully specified translation, conversion, calculation, or execution tasks.
---

# Define Problems Before Prompts

This is an executable problem-definition workflow, not a prompt-polishing template. The model makes semantic judgments; the offline runtime enforces routing, evidence binding, question limits, state transitions, and stop conditions.

## Route first

Preserve the request exactly in `schemas/request-envelope.schema.json`. Judge whether deliverable, inputs, and acceptance checks are sufficient. Mark decisive unknowns when an answer could change the route, success test, risk, or next action. Mark high-risk value decisions for career exit, separation, medical, legal, or investment choices.

```bash
scripts/dpbp gate --offline < request-envelope.json
```

Keep the returned `gate_receipt` unchanged.

- `execute`: perform the clear task directly. Do not create a Problem Spec or ask diagnostic questions.
- `define`: load only the returned `resources`, beginning with `references/core.md`.
- `defer_to_user`: also preserve the high-risk boundary. Clarify evidence and tradeoffs without choosing for the user.

## Build and validate the spec

```bash
scripts/dpbp init < request-envelope.json
scripts/dpbp validate < problem-spec.json
scripts/dpbp render < problem-spec.json
```

Fill the twelve fields with grounded facts, explicit hypotheses, decisive unknowns, success evidence, failure conditions, and one reversible evidence test. A provisional spec may propose success criteria as strings. Before `confirmed`, both the real-world outcome and every structured success criterion must cite active post-start user evidence; a model-proposed criterion needs explicit user confirmation and must add an observable dimension rather than rewording “better.” Ask at most three questions. Never convert a tool, app, or polished prompt into the goal. Exit `0` from `validate` is required before rendering.

## Run the evidence loop only when continuation is real

Read `references/runtime-loop.md`, then:

```bash
scripts/dpbp start --state /explicit/state.json --max-rounds 3 < problem-spec.json
scripts/dpbp resume --state /explicit/state.json < answer.json
scripts/dpbp status --state /explicit/state.json
scripts/dpbp advance --state /explicit/state.json < revised-spec.json
scripts/dpbp amend --state /explicit/state.json < amendment.json
scripts/dpbp decide --state /explicit/state.json < user-decision.json
```

Every mutation carries `expected_revision`. Cite later answers with `source_id`; do not silently replace evidence. `advance` must either ask a new bounded round, reach `ready_for_answer`, wait for a user-owned decision, or stop at the round budget. After `awaiting_user_decision`, record one fresh `user_input` for each unresolved `tradeoff_id`; its selected span becomes `decision_input:<id>` and that exact span must express a committed choice. The loop remains in `awaiting_user_decision` until every listed tradeoff has one unique decision. A decision phrase elsewhere, “I cannot decide,” a question, background facts, or a second decision for an already-covered tradeoff cannot form the terminal event. Earlier diagnostic answers cannot double as the final choice, and the host must authenticate who supplied each new input.

Do not persist ordinary clear tasks or sensitive details without a genuine continuation need. The runtime cannot discover a person's true goal; it makes assumptions, provenance, unresolved choices, and stopping behavior auditable.
