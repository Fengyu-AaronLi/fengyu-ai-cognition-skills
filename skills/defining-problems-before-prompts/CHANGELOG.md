# Changelog

## 0.3.0-rc.4 · local candidate

RC.3 returned to RED after a frozen independent tail audit found semantic convergence and evolution-workspace corruption paths. RC.4 turns that fixed finding set into structural regression contracts.

### User-confirmed convergence

- Changes confirmed success evidence from free strings to sourced `{value, sources}` criteria.
- Requires confirmed outcomes and criteria to cite active post-start answers or amendments; original-request-only, superseded and model-invented acceptance criteria cannot certify convergence.
- Rejects meta-rewording such as “record whether I become better” unless the user confirms a more determinate observable dimension.
- Rejects “I cannot decide,” undecided language and questions as terminal user decisions while preserving committed negative options such as “I decide not to resign.”
- Recursively scans model-semantic fields for high-risk verdicts while excluding original user text and source quote subtrees.

### Evolution fail-closed hardening

- Rejects state/ledger path aliases, non-finite JSON numbers, empty or colliding event IDs and reserved namespaces before mutation.
- Validates receipt ID, outcome/failure-code polarity and actor linkage.
- Makes stopped workspaces immutable to new mutations while preserving exact replay of previously committed events.
- Returns the persisted stopped phase when saturation fires and prevents cycle/promotion namespace collisions from corrupting the ledger.

### Multi-tradeoff state closure

- Keeps the loop in `awaiting_user_decision` after only a proper subset of value tradeoffs has been decided.
- Rejects a new decision event for an already-covered `tradeoff_id` without writing state, while preserving exact replay of the original event.
- Requires unique decision IDs, unique expected tradeoff IDs and complete coverage before `user_decision_recorded` becomes valid.

### Evidence

- Problem loop: 21/21.
- Evolution loop: 29/29.
- Independent agent-context targeted replay: 51/51.
- Full local contract suite: 134/134 in both maintainer and independent replay.
- No fresh `0.3.0-rc.4` host-model score is claimed.

## 0.3.0-rc.3 · local candidate

An independent tail audit moved RC.2 back to RED after reproducing three provenance bypasses. This round preserves those failures and closes them without expanding the prompt surface.

### Decision evidence closure

- Requires the exact selected span, not merely another sentence in `user_input`, to contain the explicit user-decision marker.
- Rejects a background fact selected from input that happens to contain an unrelated “I decide” sentence elsewhere.
- Keeps fresh post-definition input, exact spans, tradeoff IDs and host-side identity/semantic checks as separate boundaries.

### Evolution evidence closure

- Checkpoints the canonical digest of the RED receipt observed by `failure_observed`.
- Requires `close-cycle` to reuse that exact base receipt; matching only case and input is insufficient.
- Makes close-cycle replay idempotent only for a byte-equivalent canonical payload.
- Routes repeated `init` through the full ledger/head/state checkpoint validation path.

### Evidence

- Problem loop: 15/15.
- Evolution loop: 14/14.
- Full local contract suite: 113/113 before the final independent tail rerun.
- No fresh `0.3.0-rc.3` host-model score is claimed.

## 0.3.0-rc.2 · local candidate

This round converts independent review failures into regression contracts instead of adding more prompt prose.

### State-loop closure

- Requires a fresh, explicit `decision_input:<id>` after `awaiting_user_decision`; earlier diagnostic answers cannot be reused as the final value choice.
- Rejects background facts presented as decisions and keeps host-side user authentication as an explicit limitation.
- Keeps zero-question provisional states in `needs_reassessment` and reports only currently executable actions.
- Rejects low-information confirmation targets such as “好、更好、变优秀” and outcome-as-evidence circularity.
- Advances the Problem State schema to `2.1`.

### Evolution and packaging closure

- Binds failure, base, candidate, and reproduction receipts to the manifest case input hash.
- Adds a derived-state SHA-256 checkpoint to every evolution ledger event and rejects state-only tampering.
- Rejects allowlisted files reached through a symlinked parent directory, not only symlinked leaf files.
- Expands the full local contract suite to 109 tests.

### Remaining boundary

- Unkeyed checkpoints do not resist simultaneous state-and-ledger rewriting.
- Actor identity and run artifacts remain self-attested and hash-declared.
- No fresh `0.3.0-rc.2` host-model result is claimed.

## 0.3.0-rc.1 · local candidate

This candidate turns the one-shot diagnostic into two explicit loops without allowing either loop to decide the user's values or silently rewrite the Skill.

### Problem-definition evidence loop

- Adds `advance`, `amend`, `status`, and `decide` to the existing `start` and `resume` state protocol.
- Promotes answers into hash-bound evidence sources and rejects unknown, tampered, or superseded spans.
- Allows `confirmed` only inside state-aware convergence with no decisive unknowns or pending questions.
- Adds bounded rounds, terminal phases, stop reasons, read-only status, answer correction history, and explicit user-only high-risk decision events.

### Failure-driven evolution loop

- Adds source-only maintainer runtime `scripts/dpbp-evolve`.
- Adds append-only hash-chain events, idempotent event IDs, run-receipt binding, distinct author/reproducer/reviewer roles, sealed holdout lifecycle, promotion gates, iteration budget, and saturation stop.
- Reclassifies the four repeatedly used cases as public regression cases, not untouched holdouts.
- Makes `evals/suite-manifest.json` the hash-bound source of truth read by the offline runner.

### Packaging and discovery

- Adds OpenAI discovery metadata and a reproducible explicit-allowlist lean bundle.
- Keeps tests, eval history, and maintainer evolution tooling outside the install bundle.
- Adds a negative trigger boundary for fully specified translation, conversion, calculation, and execution tasks.
- Compresses `SKILL.md` into a progressive dispatcher and moves state details to `references/runtime-loop.md`.

### Evidence boundary

- No fresh `0.3.0-rc.1` host-model result is claimed.
- The candidate remains local, uncommitted, unpushed, unpublished, and not production-approved.

## 0.2.0-rc.6 · local candidate

This release candidate replaces the prompt-bundle architecture with an executable Agent Skill package.

### Added

- Offline `gate`, `validate`, `render`, `start` and `resume` commands.
- Machine-readable request, Problem Spec and state schemas.
- Exact evidence-span validation for facts and hard constraints.
- Deterministic progressive-resource routing and twelve-section rendering.
- Structured exit codes, atomic state writes and idempotent answer replay.
- Runtime, architecture and frozen same-input evaluation tests.
- Domain adapters loaded only for AI efficiency, AI product and high-risk decisions.
- Offline `help`, `version` and read-only `doctor` commands.
- Semantic stop-point checks derived from preserved host-model failures.

### Changed

- `SKILL.md` is now a 101-line dispatcher instead of a 241-line policy prompt.
- The standalone paste-in prompt is a legacy compatibility artifact, not the installation path or product proof.
- The old 4/4 transcript result is labeled as prompt-behavior evidence rather than runtime evidence.

### Unchanged boundaries

- The runtime does not claim to infer a person's true goal.
- Career exit, relationship, medical, legal and investment choices remain user-owned.
- Clear translation, conversion and calculation tasks still pass through without a Problem Spec.
- Candidate remains local, unpushed and unpublished.

### RC.2 regression hardening

- Rejects high-risk delay tactics, option-preservation defaults and drafted replies hidden inside otherwise valid fields.
- Keeps AI-efficiency work at workflow loss and a non-AI baseline until the decisive unknowns are resolved.
- Rejects product deliverables masquerading as real-world outcomes and implementation options introduced before demand evidence.
- Rejects competitor pricing pages as proof of this project's demand and detects unsourced Chinese half-duration thresholds.
- Requires one to three high-value questions when the real outcome is unknown and several decisive unknowns remain.

The failures that produced these checks remain under `evals/retest/runtime-v0.2/`; they are not counted as passing evidence.

### RC.3 regression hardening

- Rejects ungrounded option consequences that bias a high-risk decision while preserving explicitly uncertain framing.
- Rejects candidate use-case menus and vendor names hidden inside AI-efficiency questions while allowing the phrase “non-AI baseline”.
- Rejects AI-product form bias, conditional target reassignment and any prototype introduced before demand evidence.
- Detects unsourced “at least one group/kind/item/record” evidence thresholds.

The RC.2 host-model failures remain under `evals/retest/runtime-v0.2-rc2/`.

### RC.4 typed problem coverage

- Makes `decisive_unknowns[].category` and `questions[].addresses` mandatory runtime and state contracts.
- Requires domain-specific coverage for career exit, AI efficiency and AI product definition instead of accepting twelve well-formed but incomplete sections.
- Adds a career-exit progressive playbook covering financial capacity, alternatives, health status, desired outcome, risk tolerance and the actual decision target.
- Rejects an AI/tool label as the efficiency outcome, single-sample claims of a dominant loss or representative baseline, solution changes hidden in `change_evidence`, and sunk-cost language reintroduced through product questions or the rewritten problem.
- Preserves the exact twelve-section renderer and zero-resource pass-through for clear tasks.

The RC.3 host-model failures remain under `evals/retest/runtime-v0.2-rc3/`. RC.4 was later rerun on the frozen four inputs and scored 4/4 under an independent semantic audit, but an independent code audit still blocked that version.

### RC.5 route and state binding

- Embeds the exact request envelope and a recomputable gate receipt in every Problem Spec; validation reruns the gate and binds request identity, hash, domain, mode, resources, route rule and execution permission.
- Gives every decisive unknown a stable ID and requires questions to reference those IDs, closing label-only coverage.
- Adds a structured next-test boundary: `evidence_collection`, `evidence_only=true`, and `solution_commitment=none`.
- Rejects trim-empty required text, duplicate fact values across different source spans, and the high-risk decision paraphrases found by independent review.
- Derives pending questions from the validated spec and protects resume with an expected revision, local file lock and atomic replacement.
- Records JSON Schema and runtime validation as co-normative, while explicitly declining to claim exhaustive natural-language semantic proof.

RC.4's four host outputs passed their semantic audit, but RC.4 remained release-blocked because its gate receipt and state were not structurally bound. Those artifacts remain under `evals/retest/runtime-v0.2-rc4/` and are not relabeled as RC.5 evidence.

RC.5's final host retest was attempted in four fresh processes, but all four stopped at the Codex CLI account usage gate before a model response. RC.5 therefore has 4 attempted and 0 completed host trials, not a 0/4 or 4/4 score. The exact environment and error are preserved under `evals/retest/runtime-v0.2-rc5/`.

### RC.6 discovery metadata correction

- Reduces the YAML `description` to trigger conditions only, so the host must load the full Skill instead of treating frontmatter as a workflow summary.
- Leaves the executable runtime contract unchanged from the reviewed RC.5 code.
- Requires fresh hashes, offline verification and a new host gate record; RC.5 evidence is not silently relabeled.

## 0.1.0 · superseded local candidate

Behavioral rules, four frozen evals, provenance and launch materials existed, but runtime capability depended on loading the entire `SKILL.md`. There were no scripts, schemas, automated tests or resumable state. This version is retained as baseline evidence, not as the current architecture.
