# FinDVer Agent repository instructions

This repository implements an offline financial-verification runtime plus an additive
generic evaluation-Agent path. Read these files before changing code:

1. `docs/PROJECT_CONTRACT.md`
2. accepted records in `docs/adr/`
3. `docs/STATE.yaml`
4. `docs/SESSION_HANDOFF.md`

The contract is immutable unless the user explicitly changes it. Keep the original
one-call FinDVer path available as a baseline. The FinDVer execution mode must retain
exactly `search_report`, `read_paragraphs`, `calculator`, and `submit_answer`. The
generic execution mode may use only a task-profile-selected subset of reviewed,
code-owned bounded skills; configuration must never dynamically import tool code.
Never add per-example answer rules or copy private gold, scorer code, scorer outputs,
builder feedback, secrets, or unrestricted execution/network tools into either Runtime.

Before implementation work, run the recovery commands documented in
`docs/SESSION_HANDOFF.md` and the current test suite. After each phase, run
`scripts/context_checkpoint.py`, update the handoff, and make one focused commit.
Runtime and scorer code/build contexts must remain separate.
