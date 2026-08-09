# RC.5 same-input host retest

## Result

**BLOCKED: 0 completed trials out of 4 attempted.**

The exact same four frozen inputs were launched in four fresh Codex CLI processes. Every process exited `1` at the account usage gate before the model produced a response. There is no defensible per-case PASS/FAIL score and no `raw/DPBP-*-output.txt` artifact.

This result must not be rewritten as either 0/4 or 4/4:

- It is not 0/4 because the model never attempted the tasks.
- It is not 4/4 because RC.4 outputs cannot prove RC.5 behavior after the runtime contract changed.

## What is verified for RC.5

- 67/67 unit, architecture and runtime tests passed after the final version bump.
- Four frozen offline runtime cases passed; each gate was repeated 100 times with one byte-identical output per case.
- `doctor` passed all 11 local asset checks.
- Independent release review found no remaining blocking defect after the duplicate-fact-value fix.
- Clear translation still routes to `execute` with `resources=[]` in the offline runtime.

## What remains unverified

- A fresh host model can successfully construct and validate the new envelope-bound RC.5 Problem Spec.
- RC.5 preserves RC.4's 4/4 semantic behavior under the four frozen pressure inputs.
- Cross-model, cross-language and repeated stochastic stability.

Environment, exact error and hashes: [`environment.md`](environment.md).
