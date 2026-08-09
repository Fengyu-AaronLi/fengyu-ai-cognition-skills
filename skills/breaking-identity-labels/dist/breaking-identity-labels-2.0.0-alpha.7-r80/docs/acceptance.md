# V2 Acceptance Contract

以下治理命令仅在完整源码仓库可用；最小安装包不含测试、工作流和审计脚本，因此这些命令不可用。发行包中的 `SKILL_DIR` 必须保持只读，运行产物只写入 Skill 之外的唯一 `WORK_DIR`。

V2 is accepted only when the runtime, not the prose alone, satisfies every gate below.

## Gate 1: Package

- CLI, versioned runtime and governance schemas, template, tests, references, blocker-driven workflow and runnable acceptance commands exist.
- `SKILL.md` orchestrates the runtime instead of reproducing the entire implementation in prose.
- Runtime requires Python 3.10 or newer and only the Python standard library.
- Supported platforms are macOS and Linux with Unix `fcntl`; native Windows is explicitly rejected or documented as unsupported.
- Package build, verify and no-overwrite install commands are documented and executable.
- User prose has file/stdin ingress for scaffold and init, structured-file ingress for record, and file ingress for experiment confirmation and review. Operator examples never interpolate that prose into shell argv.
- `scaffold --out`, `prepare-analysis --out`, `compile --out` and `render --out` atomically create one new artifact and refuse an existing path or symlink.
- Package verification runs both the stateless `scaffold → prepare-analysis → compile → validate → render` smoke and an external-temporary-directory persistent `init → plan → start → record → review → replay → next` lifecycle. It requires five events, revision four, a complete terminal action and no mutation of package bytes.

## Gate 2: Evidence lineage

- Labels, judgments, observations and counterexamples point to an exact quote and character range in a stored evidence item.
- Each label's declared source type matches the local source cues around that exact span, including mixed-source inputs.
- A mismatched range is rejected with `source_span_mismatch`.
- A label copied into the behavior field is rejected with `label_is_not_behavior`.
- Missing evidence remains unknown or hypothesis; it is never backfilled from a label definition.

## Gate 3: Policy

- Reported formal diagnoses remain reported diagnoses.
- Medical changes are rejected with `medical_plan_change`.
- Breakup, resignation, project shutdown and similar irreversible actions are rejected as experiments with `high_cost_experiment`.
- Positive replacement identities are rejected with `positive_relabel`.
- Unreported feelings, motives or promises are rejected with `unreported_personal_claim`.
- Unreported inner states presented as causes are rejected with `unreported_psychological_cause`.
- AI-generated diagnosis confirmation is rejected with `diagnosis_confirmation_generated`.
- Stable preferences without impairment, conflict or a change request use route mode `preference_acknowledgement`, finish with case status `no_intervention`, and cannot receive a corrective experiment. If a capability verdict makes a mixed input enter `deconstruct`, the experiment may test only that verdict and still cannot target or force exposure against the reported preference.
- Reported severe functional impairment routes to `support_escalation`; medical changes and immediate safety risks produce user-visible real-world support boundaries.
- Safety output preserves the reported subject, target, means and poison-exposure state, never invents a means or symptom, and cites only location-neutral real-world actions from `references/safety-boundaries.md`.
- Explicit current-user intent can be conservatively upgraded by composing same-sentence time, action, target and available-means evidence; clear self-harm or other-harm cases must not fall through to an identity-label question.
- Direct questions about a label do not become self-identification, third-party diagnoses do not become the user’s diagnosis, local negation does not erase a separate diagnosis, and nested quoted observations are not duplicated as independent user evidence.

## Gate 4: Experiment compiler

A planned experiment must contain exactly one named primary variable, a positive duration, an observable action, fixed conditions, measures, separate support and weakening outcomes, and a reversibility statement. It may test only a narrow behavior claim.

`prepare-analysis` must expose a stable, source-span-bound `target_id` for every runtime judgment. An operator must be able to copy that public ID into `target_judgment_ids` and compile successfully without reconstructing an undocumented identifier from source code.

The stateless `compile` command must merge a saved scaffold and a human-completed analysis into one `planned`, revision-1 case, run the same validation gates as persistent planning, refuse silent output overwrite and produce a case that can be passed directly to `validate` and `render`.

## Gate 5: State and replay

The supported lifecycle is:

```text
drafted -> planned -> observing -> reviewed
```

Each transition increments `revision` and appends a full snapshot to `events.jsonl`. A separate `events.head.json` records the latest count and hashes. `replay` must reject a modified snapshot, broken hash chain, invalid event/state transition or tail rollback that does not also rewrite the head.

`start` requires an explicit experiment-confirmation file. Unrelated nonempty bytes must fail without a state write. The start event must bind the exact text and its hash to the pre-start case ID, revision and canonical experiment digest; replay must reject a rehashed scope mismatch. This is a local consistency check only: file bytes and event hashes cannot authenticate human identity or prove that a real user authored the consent.

Every persistent write and `status` must replay before loading state. Across adjacent events, non-record transitions preserve the complete evidence array; a record transition preserves the exact old prefix and appends one item. Start, record and review may change only the fields authorized by that event.

When `record` receives an operation ID, the pair of operation ID and semantic payload fingerprint must be exactly-once: an identical retry returns the original snapshot without a new event, a conflicting retry is a zero-write failure, and replay rejects duplicate operation IDs or incomplete operation metadata. Retry detection precedes revision and event-clock preconditions after the existing chain has been verified.

An interrupted transaction may be recovered only under a pre-existing exclusive case lock and only when the journal shape, transaction directory, staging files, backups and resolved paths are all confined to that case. Malformed journals, traversal, symlink escape, a missing lock and unknown artifacts must fail closed. `doctor`, `status`, `replay` and `next` must not create a missing lock. A read-only `doctor` reports state without repairing it; `recover` must replay after recovery and must not turn a missing lock into a valid case. Neither command is an undo mechanism for already committed revisions.

The hashes are tamper-evident checks, not authenticated signatures. Rewriting the log, materialized case and head together remains outside the guarantee.

## Gate 6: Read-only workflow loop

`next` must be read-only and return one safe transition for `drafted`, `planned`, `observing` and `reviewed`. Only `deconstruct` may use the ten-part report and experiment lifecycle. Preference and clinical-only cases complete without an experiment or observation task. `needs_information` asks one route-changing question. Functional impairment and safety cases return only real-world support actions and omit identity analysis. Integrity failure blocks all next steps.

## Gate 7: Offline tests

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s tests -p 'test_final_forward_regressions.py' -v
python3 evals/run_v2_evals.py
python3 evals/validate.py
make workflow
```

Required result:

- Unit and lifecycle tests: zero failures and zero errors.
- Held-out router set: at least 30 cases, trigger macro F1 at least `0.90` and mode accuracy at least `0.90`.
- All 13 frozen clinical boundary cases pass.
- All 13 injected critical policy violations are blocked.
- The final forward regression file closes the frozen 5-case forward run, 32 policy mutations and 2 state-integrity minimum reproductions; a separate post-fix retest must preserve raw commands and frozen hashes.
- Original four baseline and two upgrade inputs retain their required routing boundaries.
- Offline result JSON binds the exact runtime, evaluator and all four input datasets. Any hash drift invalidates its use as current evidence.

Offline deterministic evaluation does not prove universal model behavior. Live model runs must be reported separately with model identifier, settings, raw output and grader method.

The baseline verifier must bind the four pre-Skill raw records, frozen prompts, rubric and baseline report. It may claim only byte integrity and correspondence. It must set `causal_improvement_claim: false` and must not guess the unexposed model or reasoning setting.

Historical analysis replay and fresh current-candidate evidence are separate gates. `evals/live-e2e-manifest.json` must honestly identify the saved R64 analyses as `historical_analysis_replay`; replaying them through current runtime checks compatibility but is not a new model run. `evals/fresh-candidate-e2e-manifest.json` must bind the four frozen prompts to the current `SKILL.md`, runtime, `problem-spec.md`, analysis/case Schema and template, plus four distinct runner task records and a distinct reviewer task. For C01 to C03, the verifier replays the freshly saved analysis through `scaffold → compile → validate → render` byte for byte. C04 uses the preference route without model analysis or compile. The reviewer binds every intermediate hash and fixed checks for identity verdicts, diagnosis preservation, preference non-correction, uncertainty, experiment falsifiability and reserved personality judgment. Unexposed model or reasoning values must say `not_exposed`. One orchestrator-attested run per case cannot support an authenticated-model, universal or clinical claim.

## Gate 8: Reproducible demo

`make demo` must rebuild a complete case under `examples/real-run/` from checked-in input and analysis fixtures, including `events.head.json`. It must work when the output directory already contains the two source fixtures and must not delete unrelated files. `scripts/verify_demo.py` must independently reject stale Skill/runtime bindings and any artifact hash drift, then rerun validate and replay. `make verify` must validate schemas, policy, workflow, state replay, route-specific report generation, evaluation metrics, historical replay and the separate fresh current-candidate sample.

## Gate 9: Release honesty

A passing local build is still a local candidate. Commit, remote, push, publication and public availability require separate evidence.

Source, demo and package validation may report a previous frozen release gate as `non_current` while the candidate is being changed. That is acceptable only when the stored boundary remains `local_unpublished`, no publication action is recorded and the gate itself fails closed with `release_eligible: false`. This state is not release proof; only a newly frozen candidate and `check --strict-release` may establish current local eligibility.

## Gate 10: Evolution run and candidate snapshot

- The current executable workflow is `workflows/v78-final-release.json`. v68 is a compatibility predecessor; v65, v51 and historical red workflows remain evidence and cannot be resumed as current green runs.
- Every command uses a static argv array, binds the executed script hash and stores a snapshot of declared inputs, the controlled environment, stdout, stderr and exit code. Every run-local evaluation, demo and package artifact used as evidence is consumed and hash-bound by a later verification step.
- A completed run stores the exact seven-part artifact snapshot. Status fails closed when runtime, schemas, tests, demo, package, governance or workflow drift.
- Unknown Schema keywords, malformed Schema structure, Python boolean-as-number coercion and invalid date-time values are rejected.
- Test generation is add-only. Existing test changes require a Schema-valid semantic migration receipt with a continuous hash history and file-backed evidence. A sealed red-ledger test hash may use only that same-path verified chain to reach current bytes; red evidence files themselves always require exact current bytes. Workflow command snapshots must bind the current test head and every file actually used to validate that migration chain, rather than rejecting the historical test hash before the red verifier runs.
- The frozen test manifest and `tests_tree_sha256` cover both registered test modules and the complete non-code support-file inventory under `tests/`.
- Candidate-bound blindspot discovery runs before the full regression, generates distinct nonce-free bodies within each strategy and fails the workflow on any missing semantic signal.
- Concurrent compliant writers receive a non-blocking lock failure. Freeze and audit use one release-state/run lock order so compliant races cannot lose updates. Locks are advisory and do not claim protection from non-cooperating writers.

## Gate 11: Completed-run-bound audit and blocker loop

- Freeze requires `--completed-run-dir` and binds the exact completed run-state hash, event count/head, receipt tree, workflow and completed artifacts.
- A real frozen state accepts only completed-run-bound audit receipts `1.2`. Each command script and pre-execution input snapshot must also match the hashed preregistration. Versions `1.1` and `1.0` are legacy fixture formats and cannot satisfy the current strict gate or current blocker-resolution path.
- Four current, file-backed internal isolated audits are required: attribution, clinical/safety, state integrity and release package. The `independent_*` machine IDs are legacy protocol identifiers and do not mean third-party audit or authenticated actor identity. A passed receipt cannot contain a failed command.
- Open blockers are hash-bound, reject a new root run, survive freeze and are inherited by next iteration. A blocker cannot be closed by changing status in place.
- `--resolve-blocker` requires a receipt that binds the original blocker, source predecessor, completed repaired run, separate implementation/regression evidence and a passed audit finding tied to a real successful workflow command.
- Resolution evidence is continuously revalidated and projected into the release state. Missing or changed evidence invalidates the successor and release gate.

## Gate 12: Security and durability claims

- Local hashes, event heads, audit receipts, package manifests and blocker resolutions are consistency checks, not digital signatures or external authenticity proof.
- Controlled command environments reduce parent-secret inheritance but do not sandbox filesystem or network access.
- `fcntl` locks are cooperative, platform-specific and not validated on network or synchronised filesystems.
- The evolution controller does not promise crash-atomic commit across every state, event and receipt file, nor automatic rollback of command side effects.
- The package audit must prove build, directory verify, archive verify, install, installed verify and three-form equivalence all share the frozen candidate's `package_tree_sha256` and one identical `PACKAGE-MANIFEST.json` byte hash. Manifest verification rejects undeclared top-level and file-record fields.
- Formal release export may only extract the authenticated ZIP already inside the frozen completed run. It refuses overwrite, checks directory/ZIP equivalence and never rebuilds from the active source tree after the gate.
- Strict release success still reports `local_unpublished` and `publication_actions_performed: false`.
