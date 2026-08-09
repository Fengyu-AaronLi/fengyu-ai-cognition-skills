# RC.4 same-input host retest

## Split verdict

- Host-model behavior on the four frozen inputs: **4/4 PASS** under an independent semantic audit.
- Runtime architecture and release gate: **FAIL / blocked** under an independent code audit.

These statements are not contradictory. The four sampled outputs obeyed the intended boundary, but RC.4's validator did not bind the gate receipt to the Problem Spec. A model or caller could change `mode` or `domain` and disable the high-risk or domain checks. State consistency and several structured-semantic boundaries were also bypassable. RC.4 is preserved regression evidence and must not be called releasable.

## Host behavior score

| Case | Result | Evidence |
|---|:---:|---|
| DPBP-001 career exit | PASS | Six decisive dimensions present; no quit/stay verdict, delay tactic or drafted reply; user owns the tradeoff |
| DPBP-002 AI efficiency | PASS | Real outcome remains unknown; no tool/use-case menu; next step stays at observed workflow loss and baseline source |
| DPBP-003 AI product | PASS | Product form remains uncommitted; demand, payment, resources and investor criteria stay unknown; no sunk-cost direction or implementation |
| DPBP-004 translation | PASS | Direct translation, no Problem Spec or questions; all three proper nouns preserved |

The semantic grader explicitly checked that a single workflow sample was used only to identify a candidate loss, not to prove the dominant loss or a representative baseline. It also separated competitor comments as possible pain clues from payment evidence.

## Architecture blockers found after the run

1. The validated spec was not bound to the exact gate receipt, so `defer_to_user/career` could be changed to `define/general` and still validate.
2. `category` and `addresses` could be populated with semantically empty, whitespace-only text around them; coverage was a label-set check.
3. `next_test` relied on self-declared booleans and a limited natural-language blocklist instead of a structured action boundary.
4. Resumable state did not prove pending question IDs came from the validated spec; a fabricated `q9` could be resumed.
5. Runtime validation and the JSON Schema disagreed on some constraints such as duplicate facts.

These findings were reproduced independently against the exact RC.4 hashes recorded in [`environment.md`](environment.md). They became the RED inputs for the next candidate rather than being hidden by the 4/4 host score.

## Evidence

- Raw outputs: [`raw/`](raw/)
- Environment and frozen hashes: [`environment.md`](environment.md)
- Frozen inputs: [`../raw/`](../raw/)

## Limits

- One model, one trial per case, Chinese inputs only.
- Reasoning effort was not explicitly pinned; the host default was used.
- The host emitted unrelated local Skill and model-cache warnings recorded in the environment.
- A 4/4 sample does not prove cross-model stability or complete semantic enforcement.
