# FinOASIS Progress and Recovery Log

## Current checkpoint

- Phase: Phase 2 — obligation-aware dynamic Skill routing
- Branch: `feat/findoasis-obligation-skills`
- Baseline remote `main`: `1ff41509fd40834ccca131d5100af580d46dbe9d`
- Current committed HEAD: `31dab0994339927ed628fc6475f9faf6ec476448`
- Remote main checked: 2026-08-28, after `git fetch --all --prune` and `git pull --ff-only`
- Worktree: Phase 2 source/tests plus checkpoint documents are not yet committed
- Push status: Phases 0 and 1 pushed
- Remote branch SHA: `31dab0994339927ed628fc6475f9faf6ec476448`
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

### Phase 1

- Added an isolated `findver_agent.findoasis` package; legacy v1/v2 action, state and
  prompt modules remain unchanged.
- Added all nine required obligation types, five statuses, bounded typed metadata,
  Runtime-owned deterministic IDs, dependency and cycle validation, and strict
  transition/reference invariants.
- Added model-safe obligation deltas with no `mark_satisfied`, mandatory waiver,
  arbitrary certificate, code or path escape.
- Added a strict nine-action v3 parser and bounded `SkillResult`; only the Runtime
  `apply_skill_result` transaction can satisfy an obligation.
- Added schema-v3 question state with obligation/value/program/rule/certificate ledgers,
  Skill routing history/counters, final certificate status and a 4 MiB bound.
- Added an atomic mode-0600 state store with file and directory `fsync`, deterministic
  filenames, and resume identity binding for task/report/config/Registry/policy/corpus.
- Extended configuration additively with explicit experimental v3 authorization flags,
  fixed Skill allowlist/budgets, obligation policy and optional frozen corpus identity.
  v1/v2 reject the new section; v3 rejects the legacy calculator, initial retrieval,
  long-context and incompatible review modes.
- Added compatibility freeze tests for Official Test V2 and M2 hashes, sealed archive
  members, sidecar schema v1, legacy parser rejection, and canonical v1/v2 state/prompt
  outputs.

### Phase 2

- Added conservative claim-only obligation seeding. It always creates document and
  final-verification obligations and adds numeric/rule families only for strong,
  subset-free lexical signals.
- Added an immutable, code-owned Registry for all nine v3 Skills plus a canonical
  Registry hash used by resume identity.
- Added a pure dynamic availability resolver over typed obligations, satisfied
  dependencies, configured allowlist and per-Skill budget, Runtime candidates,
  evidence-bound values, frozen-corpus validity and finalization fallback.
- Added a bounded v3 prompt builder that exposes only currently available contracts.
  It includes bounded search snippets and exact text only from already-read ledger
  entries, labels all report-derived content untrusted, and never dumps hidden Registry
  contracts or unavailable schemas.
- Extended v3 state with hash-checked exact evidence text, phase attempt budgets,
  aggregate usage, bounded errors, report search history, predictions and close state.
  Attempt charging is persisted before model execution.
- Added the independent `FinOASISAgent` and dispatched protocol v3 before construction
  of legacy state, prompt or retrieval objects. Phase 2 executes only report search and
  paragraph reads; later Skills fail closed until their implementation phases.
- Added unavailable-call rejection with charged attempt, protocol error and rejection
  metric but no control, obligation or ledger mutation.
- Added scripted integration coverage for IE-only dynamic exposure, adversarial hidden
  Skill calls, exact read evidence visibility and interruption/resume without repeated
  search or attempt credit.

## Baseline tests

- `.venv/bin/python -m compileall -q src scripts tests`: passed.
- `.venv/bin/pytest -q -s --basetemp=.pytest_cache/basetemp`: 289 passed in 3.18s.
- `git diff --check`: passed.
- Expected existing warnings: none in this installed dependency combination.
- Environment-only note: unconstrained install selected FastAPI 0.141.1 / Starlette
  1.6.0; the virtual environment was narrowed to FastAPI 0.115.6 / Starlette 0.41.3,
  both within declared project constraints. No dependency file was changed.

## Phase 1 tests

- Focused v3/config/compatibility and legacy-regression selection: 93 passed.
- Full suite: 341 passed in 3.45s.
- `.venv/bin/python -m compileall -q src scripts tests`: passed.
- `git diff --check`: passed.

## Phase 2 tests

- Focused Phase 1/2 unit and integration selections: 101 tests passed across the final
  focused runs.
- Full suite: 391 passed in 4.18s on Python 3.12.
- `.venv/bin/python -m compileall -q src tests`: passed.
- `git diff --check`: passed.
- No model, network, scorer, Gold, official input or paid API was used.

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

## Files changed through Phase 2

- `docs/FINOASIS_IMPLEMENTATION_PLAN.md`
- `docs/FINOASIS_PROGRESS.md`
- `docs/STATE.yaml`
- `docs/SESSION_HANDOFF.md`
- `src/findver_agent/config.py`
- `src/findver_agent/findoasis/__init__.py`
- `src/findver_agent/findoasis/contracts.py`
- `src/findver_agent/findoasis/actions.py`
- `src/findver_agent/findoasis/state.py`
- `src/findver_agent/findoasis/seeder.py`
- `src/findver_agent/findoasis/registry.py`
- `src/findver_agent/findoasis/router.py`
- `src/findver_agent/findoasis/prompt_builder.py`
- `src/findver_agent/findoasis/agent.py`
- `src/findver_agent/orchestrator.py`
- `tests/unit/test_obligations_v3.py`
- `tests/unit/test_actions_v3.py`
- `tests/unit/test_state_v3.py`
- `tests/unit/test_finoasis_config.py`
- `tests/unit/test_compatibility_freeze.py`
- `tests/unit/test_obligation_seeder_v3.py`
- `tests/unit/test_skill_registry_v3.py`
- `tests/unit/test_skill_router_v3.py`
- `tests/unit/test_prompt_v3.py`
- `tests/integration/test_finoasis_router.py`
- `tests/integration/test_finoasis_resume.py`

## Unresolved issues and risks

- Python 3.11 is unavailable locally; CI must run the 3.11 leg.
- ValueRef, FinDSL and rule-specific certificate schemas will refine the Phase 1 generic
  ledgers without weakening their reference and resume invariants.
- Table context and `html_tables` are order-aligned in all 600 tracked reports but have
  no explicit foreign key; loaders must validate and fail closed rather than guess.
- Experimental v3 sealing must preserve the existing top-level evidence ledger contract
  or remain explicitly unauthorized for scorer handoff.
- Formal financial rule sources, licences, versions and review remain unavailable and
  out of scope.

## Exact next step

Implement Phase 3: additive table indexing and bounded table-region reads, then exact
paragraph/table value binding with typed source coordinates and unit/period ambiguity
that fails closed.

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
| Phase 0 | `9e896fa0c4a534b5b6d367f4b86b88452d8278f3` | pushed | `docs: record FinOASIS implementation plan` |
| Phase 1 | `31dab0994339927ed628fc6475f9faf6ec476448` | pushed | `feat: add typed proof obligation contracts` |
| Phase 2 | pending | pending | `feat: gate skills by pending proof obligations` |
