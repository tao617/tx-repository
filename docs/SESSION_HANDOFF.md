# Session Handoff

## Current state

Phase `model-b-stability-planned` completed: Prepared and offline-validated the five hash-bound Model-B dev_feedback runs under commit f173bcb6f50cabcf3e433958aa680a7319cf9b5b; no model call was made.

- Git commit at checkpoint start: `f173bcb6f50cabcf3e433958aa680a7319cf9b5b`
- Changed files: 1

## Diff summary

```text
No tracked-file diff; see files_changed for untracked files.
```

## Tests passed

- All five selected plan rows recomposed successfully against qwen3.5-27b from .env.agent, the clean committed worktree, exact task/retrieval hashes, json_object response mode, max_retries 10, 240 RPM, and 400000 TPM.
- Plan SHA256 values are 2f0a8ab72a6ca818c337df12fc61a4fb611bcba651dbd414be8de85116350cb5, b2807042131ec4e0578652cb79e633fa0a076dca97ee6193b090f4c1b089f7ae, and 4e72110cd3e47f4b267950594f7f4bfe1de89189d713c21007702dcf37a1e2f3.

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

Request explicit user approval for the five Model-B development runs (expected about 4897 calls), then execute only BRAG10, BBM25_10, BHYBRID_RRF10, M2, and BLC in the recorded order.
