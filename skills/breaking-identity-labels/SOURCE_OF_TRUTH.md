# Source of Truth

This project separates semantic judgment, runtime enforcement and release evidence.

## Authority order

1. `problem-spec.md` defines the problem, evidence classes, route outputs and non-goals.
2. `schemas/*.schema.json` define versioned machine-readable records.
3. `scripts/identity_label_case.py` enforces source lineage, route policy, state transitions and route-specific rendering.
4. `scripts/run_evolution.py` enforces candidate lineage, command receipts, test migrations, blocker carry-over and the local release gate.
5. `workflows/v78-final-release.json` is the current executable convergence workflow. `workflows/v2-evolution.yaml` is a design map; `workflows/v15-evolution.json`, `workflows/v51-final-release.json`, `workflows/v65-final-release.json`, `workflows/v68-final-release.json` and their completed runs are historical or compatibility evidence, not current completion evidence.
6. `SKILL.md` tells an agent when and how to combine semantic judgment with the runtime.
7. `templates/analysis.json` is only a drafting aid. It never overrides a Schema or policy error.

When these disagree, stop and repair the lower-authority artifact. Do not silently choose the most convenient version.

## Case-time records

- `case.json` is the current materialized state.
- `events.jsonl` is an append-only sequence of complete snapshots linked by hashes.
- `events.head.json` records the expected event count and latest hashes, so a stale or truncated log cannot replace the current materialized state while the head remains intact.
- `next` reads the validated state and returns one safe action without modifying files.
- Persistent `plan`, `start`, `record`, `review`, `status`, `doctor` and `recover` operations replay and compare the stored chain before trusting current state. `prepare-analysis` exposes a public, source-span-bound `target_id` for each judgment.
- Labels, judgments, observations and counterexamples require an exact source span. Candidate variables remain hypotheses.
- Review can update only the preregistered narrow behavior claim. It cannot validate or revoke an identity label or diagnosis.
- `start` accepts only a file-backed, explicit first-person confirmation of the current experiment and binds its exact bytes, pre-start case, revision and canonical experiment digest. These local hashes do not authenticate human identity or consent.
- Only `deconstruct` uses the ten-part contract. Preference, clinical-only, support, needs-information and safety routes have dedicated outputs and do not receive identity experiments.

## Build-time records

- `evals/test-generation-manifest.json` is an add-only inventory of checked-in test generations. Existing hashes may change only through a Schema-valid semantic migration receipt in `evals/test-migrations/`. `evals/red-evidence-manifest.json` never grants that exception to raw evidence bytes; a historical test hash is accepted only through a same-path, continuous, receipt-hash and receipt-semantics verified chain to the current test head. The evolution controller's command snapshot binds that current head and all migration-chain files it reads, so workflow orchestration and the standalone verifier share the same historical-hash semantics.
- `evals/regression-dependency-manifest.json` hash-binds stable non-test checkout inputs read by the full regression, including raw evidence read through the red ledger. Test modules remain exclusively governed by `evals/test-generation-manifest.json` and its migration history. The dependency manifest's `skill` and `repository` scopes are expanded into command receipts, so changing a dependency after execution invalidates the completed run.
- Each evolution run stores `run-state.json`, an event chain, command or external receipts, frozen input snapshots and the completed seven-part candidate artifact snapshot.
- A completed run is not a frozen release candidate. `freeze --completed-run-dir` creates a separate release state bound to the exact run-state hash, event head, receipt tree, candidate, workflow and completed artifact snapshot.
- `evals/validate.py` validates current source, demo and package bytes. During development it may truthfully report the previous release gate as `non_current`; it cannot turn that state into release eligibility. `run_evolution.py check --strict-release` remains the sole current local release authority.
- A real frozen state accepts only completed-run-bound file-backed receipt `1.2`. The controller binds the exact script and pre-execution input snapshot for every command and cross-checks both against the hashed preregistration. Version `1.1` and `1.0` remain readable only through explicit legacy fixture validation; neither can make a current candidate release-eligible or close a current blocker.
- The test manifest binds both `tests/test_*.py` and every non-code support file under `tests/`. The candidate test-tree digest covers the same closed inventory.
- `evals/baseline-evidence-manifest.json` binds the four pre-Skill raw records, frozen prompts, rubric and report. It proves only current byte integrity and correspondence; it does not prove run order, actor identity or causal improvement.
- `evals/live-e2e-manifest.json` is a `historical_analysis_replay`: it preserves R64 model analysis and replays it through later runtime bytes. It is useful compatibility evidence but is not a fresh model run on the current candidate.
- `evals/fresh-candidate-e2e-manifest.json` is the only fresh current-candidate composition sample. It must bind the current six candidate inputs, four distinct runner task records, every runtime artifact and an independent reviewer task before the verifier may report it valid. It still does not authenticate model identity, orchestrator logs, universal behavior or clinical effectiveness.
- `evals/live-retest-manifest.json` and `evals/raw/current-live-retest-v61/` are historical V61 evidence. They cannot support a current runtime claim.
- Package equivalence requires identical payload-tree and `PACKAGE-MANIFEST.json` byte hashes across directory, ZIP and installed copies. The manifest schema is closed to undeclared metadata. A formal release package may be exported only from the authenticated ZIP already stored in a frozen completed run; it is never rebuilt from the live tree after the gate.
- Untrusted prose enters through file or stdin interfaces. Operator documentation must not interpolate user text into a shell command, and all user-selected output files refuse overwrite.
- An open blocker is hash-bound, rejects a new root run, survives freeze and is inherited by the next iteration. It can be closed only through `next-iteration --resolve-blocker` with a current receipt `1.2` that binds the original blocker, predecessor, completed repaired run, implementation evidence, regression evidence and a passed audit finding tied to an executed workflow command.
- `scripts/run_release_audits.py` runs four fixed shell-free internal isolated suites and generates file-backed receipts. The three `independent_*` audit IDs are legacy protocol identifiers, not a claim of third-party audit or authenticated reviewer independence. The controller, not the harness prose, derives whether each receipt is usable.

## Integrity and isolation limits

All hashes, heads, manifests and receipts are local consistency evidence, not digital signatures. A local actor able to rewrite every related file can create a different internally consistent history. No external authenticity is claimed.

`fcntl` locks are cooperative advisory locks. They prevent two compliant controller processes from mutating the same run concurrently; they do not stop a non-cooperating process with filesystem access, and network or synchronised filesystems have not been validated.

Evolution commands receive only the explicit controlled environment and bind the command script hash before execution. This reduces inherited-secret and script-drift risk, but it is not an operating-system sandbox: the child still runs with the current user’s filesystem and network authority. The controller also does not promise crash-atomic commit across every run-state, event and receipt file or rollback of external side effects.

## Historical and portable evidence

`evals/raw/` preserves three non-interchangeable evidence levels: baseline raw byte evidence, historical analysis replay and fresh current-candidate composition samples. Historical raw outputs must not be rewritten to make a current candidate look better. A claim must name its level and use that level's current hash-valid manifest; none proves causal improvement or clinical effectiveness.

`zero-threshold-prompt.md` is a portable fallback for environments without executable skills. It lacks mechanical route classification, source-span validation, state, replay and policy exit codes and is not equivalent to the installed runtime.
