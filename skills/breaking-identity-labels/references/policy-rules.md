# Runtime Policy Rules

## Hard failures

The validator blocks these before rendering or state transition:

- source quote or offsets do not match stored evidence;
- a label's declared source type does not match the local source cues around its exact evidence span;
- a label is entered as a concrete behavior;
- a reported diagnosis is represented as independently verified or revoked by AI;
- an AI inference, social label, suspicion or formal scale result is promoted to a reported clinical diagnosis;
- a planned experiment changes medication or treatment;
- a planned experiment performs a high-cost relationship, career, education, housing or project decision;
- a stable preference receives a corrective experiment, including when a separate capability verdict makes the overall route `deconstruct`;
- reported severe functional impairment is routed as an ordinary preference or experiment;
- generated analysis replaces a negative identity with a positive identity;
- generated analysis asserts an unreported user feeling, motive or promise (`unreported_personal_claim`);
- generated analysis turns an unreported inner state into a causal explanation (`unreported_psychological_cause`);
- generated analysis confirms or establishes a diagnosis (`diagnosis_confirmation_generated`);
- generated analysis excludes, revokes or declares recovery from a diagnosis, or decides that review or treatment is no longer needed (`diagnosis_override_generated`);
- an experiment lacks one primary variable, a deadline, measures, support and weakening conditions, or reversibility;
- a review uses an identity conclusion instead of a narrow behavior classification.
- the stored route no longer matches the original evidence;
- an event type does not match its legal state transition, or the log is shorter than its current head.
- a write command starts from a materialized case that does not replay, or a later snapshot rewrites the existing evidence prefix or other fields outside that event's allowed delta.
- a case directory has no pre-existing regular `.case.lock`; read, status, replay, next and recovery must all fail closed without creating one.

## Agent judgment remains necessary

Code cannot determine whether a subtle statement is a good counterexample, whether one question would materially change the judgment, or whether a proposed variable is substantively useful. The agent performs those judgments, stores its draft in the structured record and then submits it to the policy gate.

Passing validation means the record satisfies mechanical invariants. It does not mean the psychological interpretation is true, clinically approved or complete.

The event chain is tamper-evident only while its independent head remains intact. It is not a signature or authenticity proof against an actor who can rewrite every local file. Natural-language risk detection combines exact event patterns with bounded composition of current-user intent, target and available means across one to three adjacent direct-user clauses. It remains conservative and versioned; passing the current parser is not proof that every paraphrase is safe or that a clinical risk assessment occurred. Placeholders and conditional guards protect only the local clause or span they actually qualify; they cannot license a later AI-authored feeling, motive or promise.
