# Session Handoff

## Current state

Phase `qwen3-5-formal-parity-scored` completed: Completed, sealed, verified, and privately scored all seven Qwen main rows plus four frozen extensions on 700 dev_feedback examples each; produced same-condition Model-A comparisons, frozen within-Qwen comparisons, aggregate evidence analyses, and the Qwen Model-B report without using holdout or hidden data.

- Git commit at checkpoint start: `c2d3073ee0ee3de06476ff61869ec9ad08e6fb3c`
- Changed files: 1
- Aggregate report: `docs/B_CLASS_QWEN_MODEL_B_DEV_FEEDBACK_REPORT.md`
- Qwen M2 scored 572/700 (81.71%) versus Model A M2 at 576/700
  (82.29%): -0.57 percentage points, paired 95% CI [-3.43, +2.29], exact
  p=0.772989.
- Qwen BLC and BRAG10 are immutable transport-degraded observations with 305
  and 205 failed model responses. Do not retry or tune them without a separate
  authorization.
- Private Scorer commit `6ec34204193dce0e2ed7d8644c40b31d3b5598bc`
  accepted the composable transport identity; it did not change scoring logic.

## Diff summary

```text
No tracked-file diff; see files_changed for untracked files.
```

## Tests passed

- 270 Agent tests, compileall, launcher shell syntax, git diff checks, 30 Private Scorer tests, all three networkless Scorer Compose profiles, 11 sealed-submission verifications, byte-for-byte private archive checks, empty scorer inbox, and empty Agent/Scorer container state passed.

## Tests failed or unavailable

- None

## Recovery protocol

```bash
pwd
git status --short
git log --oneline -10
cat AGENTS.md
cat docs/PROJECT_CONTRACT.md
cat docs/STATE.yaml
cat docs/SESSION_HANDOFF.md
find docs/adr -maxdepth 1 -type f -print | sort
pytest -q
```

## Next action

Keep dev_holdout and final_hidden unopened; require a new frozen plan and explicit authorization for either, and treat any Qwen one-call transport investigation as a separate experiment.
