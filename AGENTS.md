# FinDVer Agent repository instructions

This repository implements an offline financial-verification runtime. Read these files before changing code:

1. `docs/PROJECT_CONTRACT.md`
2. accepted records in `docs/adr/`
3. `docs/STATE.yaml`
4. `docs/SESSION_HANDOFF.md`

The contract is immutable unless the user explicitly changes it. Keep the original one-call FinDVer path available as a baseline. Never add per-example answer rules or copy private gold, scorer code, scorer outputs, builder feedback, secrets, or unrestricted execution/network tools into the runtime.

Before implementation work, run the recovery commands documented in `docs/SESSION_HANDOFF.md` and the current test suite. After each phase, run `scripts/context_checkpoint.py`, update the handoff, and make one focused commit. Runtime and scorer code/build contexts must remain separate.

