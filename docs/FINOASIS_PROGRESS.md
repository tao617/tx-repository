# FinOASIS Progress and Recovery Log

## Current checkpoint

- Phase: Phase 5 — frozen offline rule Skills and applicability certificates
- Branch: `feat/findoasis-obligation-skills`
- Baseline remote `main`: `1ff41509fd40834ccca131d5100af580d46dbe9d`
- Current committed HEAD: `ee910afa61c755955a58bbd62423de9878bfae00`
- Remote main checked: 2026-08-28, after `git fetch --all --prune` and `git pull --ff-only`
- Worktree: Phase 5 source/tests plus checkpoint documents are not yet committed
- Push status: Phases 0 through 4 pushed
- Remote branch SHA: `ee910afa61c755955a58bbd62423de9878bfae00`
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

### Phase 3

- Audited all 600 tracked public report files read-only: context IDs remain aligned
  with list positions, 24,839 table contexts align with `html_tables`, and 3,057 HTML
  bundles contain multiple sibling roots that require bounded compatibility checks.
- Extended `ReportSession` additively with stable table IDs derived from existing
  context positions. Legacy paragraph IDs, text and search/read semantics are unchanged;
  malformed or misaligned table HTML disables only the new table view.
- Added a bounded, deterministic HTML table parser and region reader with source
  paragraph/table identity, selected coordinates, exact raw/text cell spans, header
  paths, inferred unit/scale and explicit ambiguity flags. It never fills missing cells,
  guesses merged structure or persists raw HTML.
- Added exact `EvidenceLedgerEntry` table coordinates and source offsets, relevant-only
  table candidate discovery, prompt masking, and atomic duplicate/read rejection.
- Added immutable `ValueRef` and numeric ledger records with Runtime-generated IDs,
  unique exact evidence spans, canonical Decimal strings, typed metadata and bounded
  ambiguity flags. No float or expression execution is used.
- Reconciled deterministic table unit/currency/scale metadata with model arguments:
  trusted inference fills `unknown`, compatible aliases canonicalize, and conflicts fail
  before ledger mutation. Unresolved mandatory unit or period metadata cannot unlock
  program execution.
- Added integration coverage proving table/value Skills remain dynamically gated and
  `execute_financial_program` becomes visible only after two distinct evidence-bound
  operands satisfy the numeric and unit-period obligations.

### Phase 4

- Added an independent `financial_dsl` package with a strict recursive AST. Leaves are
  tagged `ValueRef`, `ClaimValueRef`, or one of three allowlisted `ConstantRef` values;
  raw literals, arbitrary functions, code, files and network operations have no schema.
- Enforced maximum AST depth 4, 32 nodes and 32 total leaves in both execution and
  resume validation. Operand reuse, unknown references and source-less programs fail.
- Implemented all required base, aggregate, financial and comparison operators with
  Decimal precision 50, canonical strings, explicit rounding/tolerance, percentage
  points internally and 100 basis points per percentage point.
- Defined unit, currency, scale and period semantics per operator. Incompatible types,
  FY/quarter granularity, currency/unit mismatches and zero denominators fail closed;
  negative-denominator conventions are explicit and certificate-diagnosed.
- Added deterministic claim-value parsing with exact source spans, typed units/scales,
  relation metadata and Runtime IDs. ISO dates and booleans bind exactly for type-safe
  comparisons only; every arithmetic path remains Decimal-only.
- Added full `NumericCertificate` payloads containing canonical program hash, ordered
  leaf/evidence refs, operand snapshots, result metadata, all three check outcomes,
  rounding/tolerance, claim relation and relation outcome.
- Persisted canonical AST and claim relation with each program. Resume validation
  independently recomputes the program hash, leaf index, evidence projection, operand
  snapshots, certificate payload hash and certificate-envelope link.
- Integrated execution transactionally into the v3 agent. Only a successfully validated
  numeric certificate satisfies `numeric_operation`; false claim relations remain
  explicit verified outcomes rather than execution failures.
- Added dynamic prompt summaries for bound values and parsed claim values only while
  FinDSL is available. IE and pre-binding prompts continue to hide the entire contract
  and all numeric reference metadata.

### Phase 5

- Added strict schemas for a frozen rule manifest, full rule records, predicates,
  deterministic search hits and applicability certificates. Unknown fields, duplicate
  IDs, malformed effective intervals, missing provenance and unbound certificate
  references fail closed.
- Added a confined local loader that resolves both configured members under one
  explicit root, enforces 4 MiB file bounds, checks configured manifest/records hashes,
  checks the manifest-to-records binding and verifies every rule-text source hash. It
  has no network, download, dynamic import, execution or write path.
- Added deterministic static token search filtered by jurisdiction and effective date.
  Search returns only bounded candidate metadata; only an explicit candidate read
  persists the complete record in the Rule Evidence Ledger with corpus and record
  hashes.
- Added mechanical applicability evaluation for effective date, jurisdiction, entity
  scope, required document predicates, missing metadata and explicit selected-rule
  conflicts. The complete certificate binds ordered rule/document references and its
  payload hash is replay-checked against the generic certificate envelope.
- Integrated all three Knowledge Skills transactionally. Candidate and evidence scope
  are checked against the targeted obligation and its dependencies; only conclusive
  `applicable` or `not_applicable` satisfies the obligation, while `undetermined`
  remains partial regardless of model control metadata.
- Added prompt isolation: rule search candidates are shown only when a rule read is
  available, and hash-bound read-rule metadata is shown only for applicability. Full
  rule text is never placed in a model prompt.
- Added a four-record synthetic fixture covering current, expired, other-jurisdiction
  and conflicting rules. Its manifest explicitly states that it is synthetic test data,
  not financial, accounting, legal or regulatory guidance.
- Added resume-time rebinding of every persisted rule record to the currently validated
  corpus, plus tests for manifest/records/text/certificate tampering, path escape,
  applicability mismatches, conflicts and missing dates.

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

## Phase 3 tests

- Focused table, ValueRef, state, prompt, routing and integration selection: 90 passed.
- Full suite: 455 passed in 3.10s on Python 3.12.
- `.venv/bin/python -m compileall -q src tests`: passed.
- `git diff --check`: passed.
- No model, network, scorer, Gold, official test input or paid API was used.

## Phase 4 tests

- Focused action, binding, FinDSL, prompt, state, routing and integration selection:
  114 passed.
- Full suite: 499 passed in 3.10s on Python 3.12.
- `.venv/bin/python -m compileall -q src tests`: passed.
- `git diff --check`: passed.
- No model, network, scorer, Gold, official test input or paid API was used.

## Phase 5 tests

- Focused corpus, prompt, obligation seeding, routing and integration selection:
  61 passed.
- Full suite: 514 passed in 3.40s on Python 3.12.
- `.venv/bin/python -m compileall -q src tests`: passed.
- `git diff --check`: passed.
- No model, network, scorer, Gold, official test input or paid API was used.

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
- Require formal production rule sources to receive separate authorization, provenance,
  licence and subject-matter review, plus project-contract revision before use. A rule
  certificate scorer sidecar remains unauthorized.
- Keep complete frozen rule text in the per-question Rule Evidence Ledger only; prompts
  receive bounded candidate or structural metadata according to the next available
  Skill.

## Files changed through Phase 5

- `docs/FINOASIS_IMPLEMENTATION_PLAN.md`
- `docs/FINOASIS_PROGRESS.md`
- `docs/STATE.yaml`
- `docs/SESSION_HANDOFF.md`
- `src/findver_agent/config.py`
- `src/findver_agent/financial_dsl/__init__.py`
- `src/findver_agent/financial_dsl/models.py`
- `src/findver_agent/financial_dsl/claim_parser.py`
- `src/findver_agent/financial_dsl/executor.py`
- `src/findver_agent/financial_rules/__init__.py`
- `src/findver_agent/financial_rules/models.py`
- `src/findver_agent/financial_rules/corpus.py`
- `src/findver_agent/financial_rules/applicability.py`
- `src/findver_agent/findoasis/__init__.py`
- `src/findver_agent/findoasis/contracts.py`
- `src/findver_agent/findoasis/actions.py`
- `src/findver_agent/findoasis/state.py`
- `src/findver_agent/findoasis/seeder.py`
- `src/findver_agent/findoasis/registry.py`
- `src/findver_agent/findoasis/router.py`
- `src/findver_agent/findoasis/prompt_builder.py`
- `src/findver_agent/findoasis/agent.py`
- `src/findver_agent/findoasis/table_region.py`
- `src/findver_agent/findoasis/value_binding.py`
- `src/findver_agent/report_store.py`
- `src/findver_agent/orchestrator.py`
- `tests/unit/test_obligations_v3.py`
- `tests/unit/test_actions_v3.py`
- `tests/unit/test_state_v3.py`
- `tests/unit/test_finoasis_config.py`
- `tests/unit/test_financial_dsl_v3.py`
- `tests/unit/test_compatibility_freeze.py`
- `tests/unit/test_obligation_seeder_v3.py`
- `tests/unit/test_skill_registry_v3.py`
- `tests/unit/test_skill_router_v3.py`
- `tests/unit/test_prompt_v3.py`
- `tests/unit/test_report_tables_v3.py`
- `tests/unit/test_table_region_v3.py`
- `tests/unit/test_value_binding_v3.py`
- `tests/unit/test_rule_corpus_v3.py`
- `tests/integration/test_finoasis_router.py`
- `tests/integration/test_finoasis_resume.py`
- `tests/integration/test_finoasis_table_value.py`
- `tests/integration/test_finoasis_rules.py`
- `tests/fixtures/finoasis_rule_corpus/manifest.json`
- `tests/fixtures/finoasis_rule_corpus/records.json`

## Unresolved issues and risks

- Python 3.11 is unavailable locally; CI must run the 3.11 leg.
- Formal production rule corpus sources, licences, versions, reviewer sign-off and
  contract authorization are unavailable; only the explicitly synthetic fixture is
  implemented and tested.
- Table context and `html_tables` are order-aligned in all 600 tracked reports but have
  no explicit foreign key; the additive loader validates alignment and fails closed
  rather than guessing.
- Experimental v3 sealing must preserve the existing top-level evidence ledger contract
  or remain explicitly unauthorized for scorer handoff.
- Formal financial rule sources, licences, versions and review remain unavailable and
  out of scope.

## Exact next step

Implement Phase 6: deterministic `ClaimCertificateVerifier`, certificate-aware v3
submission, mixed proof verification, budget-exhausted fallback and bounded Review
repair behavior.

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
| Phase 2 | `542de745a7f3802cd5d3aa5319888953c46dba6f` | pushed | `feat: gate skills by pending proof obligations` |
| Phase 3 | `56f45ffd7f9770c1a146cd00b14fa79a9b48deef` | pushed | `feat: bind financial values to report evidence` |
| Phase 4 | `ee910afa61c755955a58bbd62423de9878bfae00` | pushed | `feat: execute evidence-bound financial programs` |
| Phase 5 | pending | pending | `feat: add frozen financial rule skills` |
