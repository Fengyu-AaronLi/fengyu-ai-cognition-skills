# Core decision model

Use this reference only after the offline gate returns `define` or `defer_to_user`.

## Semantic work the model still owns

The runtime cannot discover a person's real goal. Infer nothing silently. Separate:

- What the user explicitly wants changed in reality.
- The question they currently asked.
- Whether a perfect answer to that question would necessarily change the desired outcome.
- Facts, hypotheses, decisive unknowns, hard constraints, pressures, sunk costs and value tradeoffs.
- Evidence that would count as success, failure or a reason to change the present judgment.

If the desired outcome is not explicit, record `status: unknown` and `value: 当前未知`. A plausible guess is not a fact.

## Problem Spec loop

1. Preserve the complete `request_envelope` and `gate_receipt` produced by `init`. Never reconstruct them from memory or edit the route metadata.
2. Draft all twelve fields in `schemas/problem-spec.schema.json`; give every decisive unknown a stable `id` and `category`, then make each question's `addresses` reference one or more of those IDs.
3. Anchor every known fact and hard constraint to an exact source span.
4. Label inferred proxy problems and hidden assumptions as hypotheses.
5. Keep `execution_allowed: false` while decisive unknowns or user-owned value choices remain.
6. Run `scripts/dpbp validate`. Correct only the reported field or evidence error.
7. Run `scripts/dpbp render`. Return its deterministic Markdown without appending the requested full solution.

The validator reruns the gate and checks envelope-receipt-spec consistency, structure, provenance and explicit boundary fields. It does not prove that a declared category, free-text action or semantic diagnosis is true.

## Stop conditions

- Ask no more than three questions. One question may address several unknown IDs, but every referenced unknown must still change the outcome, route, success test, risk boundary or next test. Each required domain category needs a concrete unknown whose ID is covered by a question.
- If the desired outcome is still unknown and there are multiple decisive unknowns, ask one to three such questions. Do not force questions when there is at most one decisive unknown or when the task can proceed without an answer.
- The next test only gathers evidence: set `action_type: evidence_collection`, `evidence_only: true` and `solution_commitment: none`. It must also be reversible, low cost and stop before committing to a solution.
- Pressure, authority and past spending are facts, not proof that a direction is correct.
- Do not introduce numeric targets that the user did not provide, including Chinese durations such as “半天”, “半个月” or “半年”, and evidence thresholds such as “至少一组/一种/一条/一项”.
- If the task is already clear, the gate must return `execute`; do not build a Problem Spec.

Natural-language red-line checks are defenses against tested patterns, not an exhaustive semantic classifier. Never use a passing regex check as proof that advice, implementation or a verdict is absent.
