# FinOASIS Progress and Recovery Log

## Current checkpoint

- Phase: Draft PR remediation complete — final review checkpoint
- Branch: `feat/findoasis-obligation-skills`
- Baseline remote `main`: `1ff41509fd40834ccca131d5100af580d46dbe9d`
- Final implementation-record commit: `bfd75227908dd160c62300e650add46f58e17b4a`
- Current committed HEAD: `04ffb9c6cfdbcadd34e5af51663f7a5acc162aac`
- Remote main checked: 2026-08-28, after `git fetch --all --prune` and `git pull --ff-only`
- Worktree: clean before this final documentation checkpoint
- Push status: Phases 0 through 8, closeout and remediations 1–5 pushed
- Remote branch SHA: `04ffb9c6cfdbcadd34e5af51663f7a5acc162aac`
- Draft PR: `https://github.com/tao617/tx-repository/pull/2`

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
- Added deterministic static token search. The current implementation ranks all frozen
  records by relevance without scope/date prefiltering and returns bounded jurisdiction,
  entity-scope and effective-interval metadata; only an explicit candidate read persists
  the complete record in the Rule Evidence Ledger with corpus and record hashes.
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

### Phase 6

- Added a deterministic `ClaimCertificateVerifier` that consumes only the submitted
  label, explanation, evidence IDs and durable v3 ledgers. It emits a complete bounded
  final certificate containing claim/submission/explanation hashes, checked obligation
  IDs, evidence and specialist certificate references, check results and failure codes.
- Revalidated paragraph evidence against the report-backed ledger and replayed every
  consumed FinDSL program and frozen rule-applicability certificate from its canonical
  inputs. Coherently rehashed result, program, rule scope and envelope tampering is
  rejected rather than trusted.
- Bound verified predictions and selective-Review drafts to an immutable final
  certificate and exact submission hash. State resume validation independently checks
  the full certificate ledger, envelope linkage, obligation coverage, specialist child
  references and prediction/draft payloads.
- Kept the final obligation pending while selective Review runs. A repaired submission
  receives a new verification certificate; a failed Review may use only a previously
  certificate-verified draft after replay against the current ledgers.
- Added an explicit forced-finalization incomplete path only for low-confidence answers
  carrying the `unresolved_obligation` risk. Unknown evidence, tamper, specialist label
  contradiction and other fatal verification failures cannot become fallback answers.
- Added unit and integration coverage for entailed/refuted mixed proofs, numeric/rule
  replay, malformed and unknown evidence, incomplete forced finalization, selective
  Review repair/fallback, and final-certificate state tampering.

### Phase 7

- Added four strict experimental configurations: obligation-only, numeric, all Skills
  with synthetic rules, and an explicitly named always-exposed ablation. Every config
  fixes Official Test, real-model and scorer-handoff authorization to false and declares
  the complete allowlist, budgets, obligation policy and rule-corpus boundary.
- Bundled the byte-identical frozen synthetic rule corpus under the Runtime config tree
  for container smoke only. Its manifest and records retain the reviewed SHA-256 values
  and explicitly disclaim production financial, accounting, legal or regulatory use.
- Extended the aggregate-only summary with validated v3 obligation, dynamic exposure,
  accepted/rejected Skill, certificate consumption, numeric, rule, usage and phase
  counters. It does not emit task IDs, claims, explanations, evidence text, rule text or
  raw failure messages.
- Added safe failure categories to v3 trace events so numeric binding/program/unit/
  period/type/relation and rule-integrity failures can be counted without propagating
  arbitrary error text to aggregate output.
- Added four tracked synthetic tasks and reports covering IE-only, table calculation,
  frozen-rule knowledge and mixed proof paths. The deterministic mock protocol runs all
  26 actions through the unchanged CLI/Runner and verifies dynamic gating plus final
  certificate composition.
- Added a read-only report-root override to the existing `/reports` mount so Docker can
  use tracked synthetic reports without adding a mount target, network, capability or
  Runtime environment secret.
- Extended public CI with the new credential-free v3 Docker smoke while preserving the
  existing Stateful M2 and 40-task concurrent smoke paths.

### Phase 8

- Accepted ADR 0011 and documented the complete obligation lifecycle, dynamic
  availability rules, exact table/value binding, FinDSL, frozen-rule path, final
  certificate replay, selective Review, failure semantics and four experimental
  conditions.
- Updated the top-level README, architecture, data boundary and test plan without
  changing the frozen project contract, Official Test V2 plan/config, M2 configuration,
  public Prediction, evidence sidecar or sealed submission contract.
- Added an operator runbook for Python, focused, in-process and root-controlled Docker
  verification plus fail-closed recovery and explicit authorization boundaries.
- Added a security audit covering Runtime authority, arbitrary-execution absence,
  filesystem/network confinement, evidence/numeric/rule integrity, persistence/replay,
  output privacy, secrets, containers, frozen hashes and residual risks.
- Added a regression proving the complete serialized v3 state remains below its 4 MiB
  bound even when individually bounded text fields are combined.
- Verified the full repository on Python 3.12.3 and an isolated CI-equivalent Python
  3.11.16 container. Both executed 530 passing tests.

### Draft PR remediation 1

- Added an always-visible, bounded Runtime projection of verified numeric and rule
  specialist certificate outcomes. Finalization and Review now receive canonical
  result/relation/check fields even when the corresponding execution Skill is hidden.
- Kept arbitrary diagnostics, full rule text, hidden Registry contracts and unavailable
  Skill schemas out of the projection.
- Added terminal-phase prompt tests for numeric and rule results plus an end-to-end
  backend that has no final label until it reads a false Runtime numeric relation from
  the next prompt.
- Focused prompt and end-to-end selection: 19 passed.

### Draft PR remediation 2

- Replaced the fixed two-ValueRef completion rule with bounded typed `OperandSlot`
  metadata and deterministic one-to-one slot matching. Explicit metric, entity,
  period, numeric type, currency, unit and scale requirements fail closed; `unknown`
  remains an explicit wildcard without allowing one ValueRef to fill two slots.
- Changed dynamic Skill gating to validate only ValueRefs attached to each numeric
  operand dependency. FinDSL execution now rejects missing required slot refs and
  global ledger values that are not attached to those dependencies.
- Added conservative threshold seeding for one report value plus one parsed claim
  value, while continuing to under-seed ordinary single-value IE statements. Full
  applicability dates are year-normalized before numeric-period de-duplication.
- Exposed typed slots in the bounded pending-obligation Prompt projection so a model
  can bind the requested metric/period rather than guessing cardinality.
- Allowed claim threshold operands, which deliberately have no report period, to
  participate in comparisons without weakening period checks for evidence-backed
  report operands.
- Added regression coverage for one report value plus one ClaimValueRef, one-to-one
  slot cardinality, metric/period mismatch, `sum`, `average`, `within_range`, missing
  required program refs and unattached global ValueRefs.
- Focused selections: 114 passed and 57 passed. Full repository: 543 passed in 4.85s.

### Draft PR remediation 3

- Added a closed `expected_relation` field (`applies` or `does_not_apply`) to
  rule-applicability obligations and made it mandatory for both Runtime-seeded and
  model-proposed obligations.
- Added conservative English and Chinese non-applicability detection; positive and
  broader knowledge claims default to the explicit `applies` relation.
- Changed final rule support from `APPLICABLE == entailed` to the truth table formed by
  certificate result × expected relation × submitted label.
- Added the expected relation and derived `claim_relation_satisfied` value to the
  bounded trusted specialist projection shown in Finalization and Review.
- Added complete applicable/not-applicable × entailed/refuted regression coverage plus
  negative-claim seeding and strict-schema tests.
- Focused rule/prompt/integration selection: 72 passed. Full repository: 546 passed in
  4.26s.

### Draft PR remediation 4

- Removed `document_not_contains` from the frozen rule predicate schema and deleted
  the partial-evidence absence branch. Version 1 now permits only positive
  `document_contains`; any negative predicate corpus fails closed during load.
- Changed frozen rule search to rank all records only by token relevance. Jurisdiction,
  entity scope and effective interval are returned as bounded candidate metadata rather
  than being used as prefilters.
- Persisted and exposed that candidate metadata while preserving full-rule-text prompt
  isolation and explicit read-before-check behavior.
- Added normal Agent-path tests that retrieve an expired US rule and a current EU rule
  under a 2024 US claim, then produce replay-valid `not_applicable` certificates from
  the effective-date and jurisdiction checks respectively.
- Focused rule/search/state/integration selection: 56 passed. Full repository: 548
  passed in 5.75s.

### Draft PR remediation 5

- Made the final document boundary explicit: every final certificate records
  `document_verification_scope=provenance_only` and
  `document_semantics_verified=false`. Document-only labels retain `label_supported=null`;
  Runtime `verified` means protocol/provenance integrity, not deterministic IE truth.
- Updated terminal Prompt and Review draft wording so the model sees the same boundary.
  Added an integration test where a valid but unrelated paragraph receives only
  provenance verification and no mechanical label support.
- Converted CAGR duration operands to years (`months / 12`, `days / 365`) and proved
  that 24 months equals two years under identical deterministic rounding.
- Rejected non-unit scale for scalar ValueRefs at binding, durable state and FinDSL leaf
  evaluation, preventing raw/base quantity disagreement across operators.
- Defined bare `$` as USD in report ValueRef binding and added a regression rejecting
  supplied EUR metadata for `$10`.
- Focused document/numeric/prompt/integration selection: 120 passed. Full repository:
  553 passed in 6.19s.

### Final remediation verification

- Re-ran the full Python 3.12 repository suite: 553 passed in 6.19 seconds.
- Re-ran compileall, launcher shell syntax, compatibility freezes, security boundaries
  and focused v3 regressions: 113 passed. The frozen rule manifest and records hashes
  remained unchanged.
- Re-ran the existing Stateful M2 Docker smoke: 8 actions, 9 model calls and verified
  selective-Review fallback.
- Re-ran the existing concurrent Docker smoke: 40/40 examples completed with configured
  and peak concurrency 32; the three-file sealed archive verified.
- Re-ran the credential-free FinOASIS v3 Docker smoke successfully through the local
  deterministic mock Gateway.
- All three smokes stopped and removed their containers and networks. Docker socket
  ownership and permissions were not modified.
- No real model, production rule corpus, scorer, Gold or Official Test V2 input was
  accessed.

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

## Phase 6 tests

- Focused final verifier, state, prompt, routing and integration selection: 49 passed.
- Full suite: 524 passed in 3.69s on Python 3.12.
- `.venv/bin/python -m compileall -q src scripts tests`: passed.
- `git diff --check`: passed.
- No model, network, scorer, Gold, official test input or paid API was used.

## Phase 7 tests

- Focused config, mock protocol, aggregate privacy, security and end-to-end selection:
  27 passed across the final focused runs.
- Full suite: 529 passed in 4.05s on Python 3.12.
- Existing Stateful M2 Docker smoke: passed with 9 model calls and verified Review
  fallback.
- Existing concurrent Docker smoke: 40/40 completed, peak concurrency 32, and its
  unchanged three-file sealed submission verified.
- New FinOASIS v3 Docker smoke: four tasks completed; 18/18 obligations satisfied;
  two FinDSL programs and two rule applicability checks passed; IE exposed no Numeric
  or Knowledge Skill; mixed final verification consumed both specialist certificates.
- Docker Engine 29.1.3 and Compose 2.40.3 were already installed. The user remained
  outside the Docker group and socket permissions were unchanged; the WSL host root path
  was used because this task environment blocks interactive `sudo` elevation.
- `.venv/bin/python -m compileall -q src scripts tests` and `git diff --check`: passed.
- No real model credential, external model, scorer, Gold or official test input was used.

## Phase 8 tests

- Python 3.12.3: compileall passed; 530 tests passed in 3.78 seconds.
- Python 3.11.16: isolated editable Docker installation with Git and repository metadata;
  compileall passed; 530 tests passed in 4.01 seconds. The only warning was the existing
  Starlette/httpx deprecation notice.
- Focused final obligation-size, prompt, FinDSL, rule and security selection: 84 passed.
- Frozen-interface diff, tracked-secret scan, Runtime bundle, sealed archive, aggregate
  privacy, patch-format and container-cleanup checks passed.
- The three Phase 7 Docker smokes cover the unchanged Runtime commit; Phase 8 changes
  only documentation and the serialized-state bound regression.
- No real model, external API, scorer, Gold or Official Test V2 input was used.

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
- Persist the complete final verification payload beside its generic certificate
  envelope and bind every verified prediction or Review draft to both objects.
- Treat conclusive FinDSL relation results and mechanical frozen-rule applicability as
  specialist label support only after deterministic replay; natural-language selection
  of those specialist inputs remains an experimental model responsibility.
- Permit incomplete fallback only at forced finalization with low confidence and an
  explicit unresolved-obligation risk; evidence-integrity failures remain fatal.
- Define avoidable-call rate as unavailable rejections divided by successful plus
  rejected Skill calls; define certificate-consumed Skill rate as terminally consumed
  specialist certificates divided by successful certificate-producing specialist calls.
- Keep the all-Skills always-exposed condition as a named ablation only; the primary
  experimental all-Skills condition retains dynamic obligation gating.

## Files changed through Phase 8

- `docs/FINOASIS_IMPLEMENTATION_PLAN.md`
- `docs/FINOASIS_PROGRESS.md`
- `docs/FINOASIS_METHOD.md`
- `docs/FINOASIS_RUNBOOK.md`
- `docs/FINOASIS_SECURITY_AUDIT.md`
- `docs/FINOASIS_TESTING.md`
- `docs/adr/0011-obligation-gated-financial-verification.md`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_BOUNDARY.md`
- `docs/TEST_PLAN.md`
- `docs/STATE.yaml`
- `docs/SESSION_HANDOFF.md`
- `.github/workflows/ci.yml`
- `deploy/wsl/docker-compose.agent.yaml`
- `configs/experimental/findoasis/M3_OBLIGATION_ONLY.yaml`
- `configs/experimental/findoasis/M3_NUMERIC.yaml`
- `configs/experimental/findoasis/M3_ALL_SKILLS_SYNTHETIC.yaml`
- `configs/experimental/findoasis/M3_ALL_SKILLS_ALWAYS_EXPOSED.yaml`
- `configs/experimental/findoasis/synthetic_rule_corpus/manifest.json`
- `configs/experimental/findoasis/synthetic_rule_corpus/records.json`
- `scripts/summarize_run.py`
- `scripts/run_finoasis_mock_smoke.sh`
- `scripts/verify_finoasis_mock_smoke.py`
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
- `src/findver_agent/findoasis/operand_slots.py`
- `src/findver_agent/findoasis/actions.py`
- `src/findver_agent/findoasis/state.py`
- `src/findver_agent/findoasis/seeder.py`
- `src/findver_agent/findoasis/registry.py`
- `src/findver_agent/findoasis/router.py`
- `src/findver_agent/findoasis/prompt_builder.py`
- `src/findver_agent/findoasis/agent.py`
- `src/findver_agent/findoasis/claim_verifier.py`
- `src/findver_agent/findoasis/table_region.py`
- `src/findver_agent/findoasis/value_binding.py`
- `src/findver_agent/report_store.py`
- `src/findver_agent/orchestrator.py`
- `tests/unit/test_obligations_v3.py`
- `tests/unit/test_operand_slots_v3.py`
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
- `tests/unit/test_claim_verifier_v3.py`
- `tests/unit/test_finoasis_configs_v3.py`
- `tests/integration/test_finoasis_router.py`
- `tests/integration/test_finoasis_resume.py`
- `tests/integration/test_finoasis_table_value.py`
- `tests/integration/test_finoasis_rules.py`
- `tests/integration/test_finoasis_submission.py`
- `tests/integration/test_finoasis_e2e.py`
- `tests/fixtures/finoasis_smoke_tasks.jsonl`
- `tests/fixtures/finoasis_smoke_reports/`
- `tests/fixtures/finoasis_rule_corpus/manifest.json`
- `tests/fixtures/finoasis_rule_corpus/records.json`

## Unresolved issues and risks

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

Push this final documentation checkpoint, wait for the final GitHub Actions run, and
leave PR #2 in Draft for formal review. A later reviewer may decide whether to promote
it from Draft; do not merge it, modify PR #1, or execute a real model, Official Test,
scorer or production rule corpus under this checkpoint.

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
| Phase 5 | `b56c0640e4f95682641db19bafa177bb21e18ba4` | pushed | `feat: add frozen financial rule skills` |
| Phase 6 | `a16f3c695c81ab61bcc2bcd16b031d2397f0dd9c` | pushed | `feat: verify proof certificates before submission` |
| Phase 7 | `e13ff6a9ba35ca3be8553697f6f91620bcfcdb7d` | pushed | `test: add FinOASIS end-to-end verification` |
| Phase 8 | `bfd75227908dd160c62300e650add46f58e17b4a` | pushed | `docs: finalize FinOASIS implementation record` |
| Closeout | `1e31013a6c9f965e0e0f1ebb0735b894a3ea691c` | pushed | `docs: record FinOASIS draft PR` |
| Review remediation 1 | `09c69449d1a3fe6f84307fd386e8c9da22888f53` | pushed | trusted specialist outcomes remain visible at submission |
| Review remediation 2 | `6f68a4d3b16148870d11269d36cce3aae67d8820` | pushed | typed one-to-one numeric operand slots and threshold path |
| Review remediation 3 | `8de51bb35a1ab3312b8671e13ecf80ff1c58a201` | pushed | explicit rule claim polarity and four-way label mapping |
| Review remediation 4 | `9e82f20d5662b60ddbdc7259af30acc96123859d` | pushed | positive-only predicates and scope-neutral rule retrieval |
| Review remediation 5 | `04ffb9c6cfdbcadd34e5af51663f7a5acc162aac` | pushed | provenance-only document scope and FinDSL unit boundaries |
| Review closeout | this checkpoint commit | pending | comprehensive Python, compatibility and Docker verification record |
