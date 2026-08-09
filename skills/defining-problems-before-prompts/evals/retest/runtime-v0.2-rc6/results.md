# RC.6 same-input host retest

## Result

**BLOCKED: 4 attempted, 0 completed.**

The exact same four frozen inputs were launched in four fresh Codex CLI sessions. The host printed each input and then stopped at the account usage gate before producing an assistant response. There are no `raw/DPBP-*-output.txt` artifacts and no per-case semantic score.

This is neither 0/4 nor 4/4. It proves only that the current external host gate prevented RC.6 model evaluation.

## Verified separately for RC.6

- 67/67 unit, architecture and runtime tests passed.
- Four frozen offline runtime cases passed; each gate ran 100 times with one byte-identical output per case.
- `doctor` passed 11/11 local asset checks.
- The discovery description now contains trigger conditions only; the executable runtime is unchanged from the independently reviewed RC.5 code.

## Still required

- Fresh host-model output for all four frozen inputs.
- Independent semantic audit of those RC.6 outputs.
- Cross-model and multi-trial runs.

Environment, session IDs, exact error and hashes: [`environment.md`](environment.md).
