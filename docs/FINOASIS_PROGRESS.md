# FinOASIS Progress and Recovery Log

## Current checkpoint

- Phase: Phase 0 — recovery and baseline
- Branch: `feat/findoasis-obligation-skills`
- Baseline remote `main`: `1ff41509fd40834ccca131d5100af580d46dbe9d`
- Current HEAD before Phase 0 commit: `1ff41509fd40834ccca131d5100af580d46dbe9d`
- Remote main checked: 2026-08-28, after `git fetch --all --prune` and `git pull --ff-only`
- Worktree at baseline: clean
- Push status: not yet pushed
- Remote branch SHA: not yet created
- Draft PR: not yet created

## Completed work

### Phase 0

- Cloned `https://github.com/tao617/tx-repository.git` and verified current remote main.
- Created the dedicated branch; no same-named local or remote branch existed.
- Read `AGENTS.md`, the immutable project contract, every Accepted ADR 0001–0009,
  current state/handoff, architecture, Official Test V2 freeze plan, the three required
  development reports, M2 config, v1/v2 action/state/prompt/orchestrator code, test tree
  and CI workflow.
- Read-only inspected Draft PR #1. It uses ADR 0010; this branch will use ADR 0011 and
  will not modify, cherry-pick, close, merge or redirect PR #1.
- Reimplemented only the safe design lessons: code-owned Registry, layered action
  validation, hash-bound resume identity, and scripted backend testing. Fixed-profile
  Skill exposure, free-text gaps, free-expression arithmetic/float use, generic state,
  and PR #1 contract changes are not reused.
- Created Python 3.12 `.venv` and installed `.[dev,gateway]`. Python 3.11 is not present
  on this host; compatibility will be exercised by repository CI.
- Determined that sandboxed Starlette `TestClient` background threads hang in this
  execution environment. Running the local suite outside that sandbox with a repository
  `--basetemp` is the verified test path; no network, model, scorer or official data is
  involved.
- Created the stable implementation plan and this recovery log.

## Baseline tests

- `.venv/bin/python -m compileall -q src scripts tests`: passed.
- `.venv/bin/pytest -q -s --basetemp=.pytest_cache/basetemp`: 289 passed in 3.18s.
- `git diff --check`: passed.
- Expected existing warnings: none in this installed dependency combination.
- Environment-only note: unconstrained install selected FastAPI 0.141.1 / Starlette
  1.6.0; the virtual environment was narrowed to FastAPI 0.115.6 / Starlette 0.41.3,
  both within declared project constraints. No dependency file was changed.

## Design decisions

- Dispatch protocol v3 before legacy state/prompt logic and keep v3 action, state,
  prompt and agent modules isolated under `findver_agent.findoasis`.
- Add table access in parallel to existing paragraphs; never renumber or alter old
  paragraph text.
- Keep Runner, Prediction, submission archive and evidence sidecar unchanged.
- Use ADR 0011 because PR #1 already occupies ADR 0010.
- Bind v3 resume to canonical experimental config, Registry, obligation policy, report
  identity and optional rule-corpus hashes.
- Apply Skill results transactionally only after strict graph and ledger validation.
- Use Decimal strings as authoritative numeric storage and structured reference-only
  FinDSL operands.
- Treat the tracked rule corpus as synthetic experimental fixture, not formal guidance.

## Files changed in Phase 0

- `docs/FINOASIS_IMPLEMENTATION_PLAN.md`
- `docs/FINOASIS_PROGRESS.md`
- `docs/STATE.yaml` (checkpoint update pending)
- `docs/SESSION_HANDOFF.md` (checkpoint update pending)

## Unresolved issues and risks

- Python 3.11 is unavailable locally; CI must run the 3.11 leg.
- v3 must not fall through the current prompt builder's unknown-protocol v1 path.
- Legacy state serialization must not acquire default v3 fields after resume.
- Table context and `html_tables` are order-aligned in all 600 tracked reports but have
  no explicit foreign key; loaders must validate and fail closed rather than guess.
- Experimental v3 sealing must preserve the existing top-level evidence ledger contract
  or remain explicitly unauthorized for scorer handoff.
- Formal financial rule sources, licences, versions and review remain unavailable and
  out of scope.

## Exact next step

Implement Phase 1 as an isolated `findver_agent.findoasis` contract/state/action layer,
add strict protocol-v3 configuration, add focused model/state/resume tests, and add
compatibility hash assertions before integrating any complex Skill.

## Safe recovery commands

```bash
cd /home/asus/2/tx-repository
pwd
git status --short
git branch --show-current
git log --oneline -10
cat AGENTS.md
cat docs/PROJECT_CONTRACT.md
cat docs/FINOASIS_IMPLEMENTATION_PLAN.md
cat docs/FINOASIS_PROGRESS.md
cat docs/STATE.yaml
cat docs/SESSION_HANDOFF.md
.venv/bin/python -m compileall -q src scripts tests
.venv/bin/pytest -q -s --basetemp=.pytest_cache/basetemp
git diff --check
```

## Commit and remote ledger

| Phase | Commit | Push | Notes |
|---|---|---|---|
| Phase 0 | pending | pending | `docs: record FinOASIS implementation plan` |
