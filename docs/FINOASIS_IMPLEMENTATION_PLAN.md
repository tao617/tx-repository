# FinOASIS Implementation Plan

## Status and provenance

FinOASIS is the experimental **Financial Obligation-Aware Selective Invocation of
Skills** method. Its Chinese name is
“面向金融事实核验的证明义务感知选择性技能调用框架”. This plan is additive to
the repository at baseline `1ff41509fd40834ccca131d5100af580d46dbe9d` and is
implemented on `feat/findoasis-obligation-skills`.

The method uses protocol v3 only from explicit experimental configurations. Protocol
v1, protocol v2, M2, Baseline, Iterative RAG, Official Test V2, the sealed three-file
submission, and evidence-ledger sidecar schema v1 remain unchanged.

## Goals

1. Persist typed proof obligations instead of transient free-text evidence gaps.
2. Treat a Skill as a bounded operation that may satisfy or validate obligations, not
   as the obligation itself.
3. Expose only Skills whose target obligations, prerequisites, configuration, and
   budgets make them currently available.
4. Bind every authoritative numeric operand to exact report evidence before executing
   a structured Decimal financial program.
5. Load financial rules only from a configured, local, read-only, versioned and
   hash-bound corpus, then verify applicability mechanically.
6. Verify document, numeric, and rule certificates deterministically before accepting
   a normal submission.
7. Provide aggregate-safe routing and certificate metrics plus credential-free IE,
   numeric, knowledge, and mixed mock smoke tests.

## Non-goals

- No official 1,700-example test access, Gold access, Private Scorer execution, or
  production model experiment.
- No arbitrary browser, internet, shell, Python, file-read, dynamic import, `eval`, or
  `exec` capability in Runtime.
- No production legal, accounting, tax, or regulatory corpus. The tracked corpus is a
  synthetic test fixture only.
- No change to the frozen Official Test V2 five-condition matrix, M2 configuration, or
  prior experiment results.
- No new scorer sidecar and no certificate fields in the evidence-ledger sidecar.
- No fixed planner-model call and no answer rules based on example ID or claim text.

## Invariant boundaries

- Runtime never reads Gold, subset labels, scorer code/output, detailed feedback, or
  private data.
- Public tasks remain limited to `example_id`, `statement`, and `report`.
- Credentials remain outside the repository and are owned only by the fixed Gateway.
- Rule Skills never use a network fallback and can read only a configured corpus below
  an approved rule root.
- Model actions cannot mark mandatory obligations satisfied, supply certificates, name
  arbitrary Skills, or provide file paths or code.
- Only a validated `SkillResult` or deterministic verifier can close an obligation.
- Existing submission archives contain exactly `predictions.jsonl`, `manifest.json`,
  and `SHA256SUMS`.
- Formal rule corpus and certificate sidecar use require separate authorization and a
  project-contract revision.

## Additive architecture

```text
Public claim + report
        |
        v
Conservative Obligation Seeder
        |
        v
Persistent Typed Obligation Graph
        |
        v
Static Registry + Available-Skill Resolver
        |
        v
Model chooses one exposed Skill for one target obligation
        |
        v
Runtime validates availability and executes the bounded Skill
        |
        v
Strict SkillResult transactionally updates ledgers and obligations
        |
        v
ClaimCertificateVerifier
        |
        v
bounded finalization / certificate-focused review / submit_answer
```

Protocol v3 is dispatched before the legacy `StateStore` or `PromptBuilder` is used.
Its action parser, state model, prompt builder, agent loop, and certificate verifier
live under a separate `findver_agent.findoasis` package. Existing v1/v2 action, state,
and prompt modules are not extended with v3 unions or default fields.

The existing `ReportStore` receives only an additive table-source view. Paragraph order,
paragraph IDs, exact text, search, reads, long-context serialization, and old return
types retain their historical meanings.

## Proof-obligation model

### Types

- `document_fact`
- `table_cell`
- `numeric_operand`
- `numeric_operation`
- `unit_period`
- `domain_rule`
- `rule_applicability`
- `evidence_conflict`
- `final_verification`

### Statuses

- `pending`
- `partial`
- `satisfied`
- `conflicting`
- `blocked`

Each obligation has a Runtime-assigned deterministic ID, type, bounded description,
status, mandatory flag, dependency IDs, evidence and certificate references, creation
and update phase/step, bounded diagnostics, and bounded typed metadata. Models use an
`ObligationDelta` to open an obligation, add a dependency, attach evidence, or request
partial/conflicting status. No model delta can mark an obligation satisfied or waive a
mandatory obligation.

State validation rejects unknown dependencies, cycles, duplicate IDs, invalid
transitions, satisfied obligations without evidence/certificates, unresolved conflicts
presented as resolved, dangling ledger references, and resume identity drift.

## Skill contract and result

The code-owned immutable Registry defines, for each Skill:

- name and strict argument model;
- target obligation types;
- deterministic preconditions;
- configured maximum calls;
- deterministic/non-deterministic flag;
- whether it produces a certificate;
- bounded available and unavailable reasons.

Initial v3 Skills are `search_report`, `read_paragraphs`, `read_table_region`,
`bind_financial_value`, `execute_financial_program`, `search_financial_rules`,
`read_financial_rules`, `check_rule_applicability`, and `submit_answer`. The legacy
free-expression calculator remains available only to v1/v2.

Every v3 Skill returns one strict `SkillResult` with bounded diagnostics and references,
not copied report/corpus bodies. The Runtime validates the result, applies it to a deep
copy of state, revalidates all graph/ledger invariants, and atomically replaces the
persisted state only after the transaction succeeds.

## Dynamic availability

The exposed set is the intersection of the static Registry, configured allowlist,
pending/partial/conflicting target obligations, satisfied prerequisites, available
evidence/candidates, valid corpus state, and remaining per-Skill budget.

- IE-only claims do not expose table, numeric, or rule Skills unless later evidence
  creates an appropriate obligation.
- `execute_financial_program` is unavailable until a numeric-operation obligation is
  active and every operand reference is bound with minimally valid type/unit/period
  metadata.
- Rule search is unavailable without a verified frozen corpus; read requires candidate
  IDs; applicability requires read rule evidence plus relevant document facts and scope
  metadata.
- Normal submit requires all mandatory obligations satisfied. Budget exhaustion exposes
  a best-effort submit that forces low confidence and records unresolved obligations.

The parser understands only the reviewed v3 action set. Runtime separately validates
the current exposure snapshot. An unavailable call consumes the already charged phase
attempt, records a bounded protocol error and rejection metric, and changes no
obligation or ledger.

## Report tables and value binding

`ReportSession` preserves the legacy paragraph tuple and adds parallel immutable table
sources. The loader verifies report context structure, uses context index as the
unchanged paragraph ID, maps table contexts to `html_tables` only when the deterministic
order/count relationship is valid, and never guesses a missing relation.

`read_table_region` returns bounded selected rows, columns and cells with header paths,
raw source offsets, inferred unit/scale, and ambiguity flags. It preserves raw text,
fails closed on unreliable row/column structure, and never fabricates merged headers or
missing cells.

`bind_financial_value` accepts only a value exactly locatable in already-read paragraph
text or table cells. A `ValueRef` stores Runtime ID, raw and normalized decimal strings,
numeric type, currency, unit, scale, period, entity, metric, source coordinates/span,
and ambiguity flags. Unknown metadata is explicit; unresolved mandatory unit/period
ambiguity remains unsatisfied.

## Evidence-Bound FinDSL

FinDSL is a bounded structured AST. Operands can reference only `ValueRef`, parsed
`ClaimValueRef`, or allowlisted `ConstantRef`; raw model-provided numeric operands are
forbidden. All authoritative arithmetic uses `Decimal` and canonical decimal-string
serialization.

Supported types start with money, percentage, basis points, count, ratio, scalar,
duration, date, and boolean. Supported operators start with add, subtract, multiply,
divide, sum, average, min, max, absolute difference, percentage change, ratio, margin,
basis-point change, CAGR, per-share, share-of-total, equality/approximate equality,
ordered comparisons, and within-range.

Percentage values are represented in percentage points; basis points convert at 100
basis points per percentage point. Operator argument order, rounding digits/mode,
tolerance kind/value, zero division, negative denominator behavior, maximum AST depth,
and maximum operands are explicit. Type, unit, currency and period mismatch fail closed
unless an operator explicitly allows the conversion or cross-period comparison.

A successful execution emits a deterministic `NumericCertificate` bound to the claim,
canonical program hash, operator, operand/evidence refs, normalized operands/result,
type/unit/period checks, rounding, claim relation and relation outcome. Only a verified
certificate can satisfy `numeric_operation`.

## Frozen rule corpus

The experimental `FrozenRuleCorpus` contains a manifest and records file with corpus
identity, schema/source versions, creation time, manifest/records hashes, provenance and
licence notes. Each strict rule record has an ID, title/text/aliases, jurisdiction,
entity scope, topic, effective interval, source reference and source hash.

The loader resolves configured paths under an allowlisted rule root, rejects escape and
duplicate/unknown/missing data, validates canonical hashes, and never downloads. Search
returns IDs, deterministic scores and short snippets only. Read adds full, hash-bound
rule evidence to the per-question ledger. Applicability mechanically checks effective
date, jurisdiction, entity scope, required document facts, predicates, missing metadata
and conflicts.

`applicable` or mechanically supported `not_applicable` can close the corresponding
obligation; `undetermined` cannot. The tracked corpus is synthetic and not production
financial guidance.

## Submission and review

`submit_answer` invokes `ClaimCertificateVerifier` before creating the unchanged
`Prediction`:

- document evidence must exist in the exact read ledger, explanation must be non-empty,
  and unresolved evidence conflicts fail normal verification;
- numeric obligations require untampered current-claim `ValueRef` and verified numeric
  certificates whose relation supports the label;
- rule obligations require read rule evidence, current corpus hashes and verified
  applicability certificates supporting the label;
- mixed claims require every applicable certificate family.

Normal certificate status is `verified`. Budget-exhausted best-effort status is
`incomplete`, forces low confidence, lists unresolved obligation IDs internally, and
never invents certificates. Review is certificate-focused; any failed repair retains
only a previously certificate-verified draft. A repair mode may expose exactly one
required Skill for a separately bounded attempt.

## Experimental configurations

Add under `configs/experimental/findoasis/`:

1. `M3_OBLIGATION_ONLY.yaml` — report search/read plus typed obligations and gating.
2. `M3_NUMERIC.yaml` — table/value/FinDSL enabled, rule Skills disabled.
3. `M3_ALL_SKILLS_SYNTHETIC.yaml` — numeric plus synthetic frozen rule corpus.
4. `M3_ALL_SKILLS_ALWAYS_EXPOSED.yaml` — explicit ablation only.

Every file declares experimental status, protocol v3, all execution/handoff authorization
flags false, strict Skill allowlist/budgets, obligation policy, and corpus identity when
applicable. None participates in Official Test V2.

## Aggregate-safe metrics

Summaries add only counts/rates grouped by enumerated obligation type/status, Skill,
certificate/check result, and failure bucket. They include routing exposure/call/reject
rates, bound-value and program outcomes, rule search/read/applicability outcomes, model
and local-Skill calls, tokens, latency and phase attempts. They never emit descriptions,
claims, example IDs, evidence/rule text, raw diagnostics, programs, or per-question
certificates.

## Phases and checkpoints

0. Recovery/baseline and this persistent plan/progress record.
1. Strict v3 contracts, state, action and configuration.
2. Seeder, Registry, resolver, prompt and dynamic-gating integration.
3. Table indexing/regions and evidence-bound value binding.
4. FinDSL executor and numeric certificates.
5. Frozen synthetic rule corpus and rule certificates.
6. Claim certificate verifier, submission, fallback and review.
7. Experimental configs, aggregate metrics, credential-free mock and Docker smoke.
8. Full compatibility/security audit, ADR 0011, documentation and Draft PR.

Each phase updates `FINOASIS_PROGRESS.md`, runs `scripts/context_checkpoint.py`, runs
focused tests plus relevant regression tests, creates a focused commit with explicit
paths, and pushes when GitHub permits.

## Acceptance criteria

- Python 3.11 and 3.12 CI compatibility; compileall and full pytest pass.
- All specified obligation, gating, table, value, FinDSL, rule, submission, resume,
  security, integration and aggregate-privacy cases pass.
- IE, numeric, knowledge and mixed credential-free tasks complete with expected Skill
  exposure and certificate behavior.
- Legacy M2 and concurrent Docker smokes plus v3 mock Docker smoke pass without real
  model credentials or external Runtime network access.
- v1/v2 behavior, M2/Official Test V2 hashes, three-file seal, and sidecar schema remain
  unchanged and are covered by regression assertions.
- No key, `.env`, model response, run output, official test, private data, production
  rule corpus or large cache is committed.
- Branch is pushed and a Draft PR documents implementation, tests, compatibility,
  security, unexecuted real experiments, and the separate authorization needed for a
  formal corpus or certificate sidecar.

## Official Test V2 isolation

FinOASIS is a new experimental capability and is not a replacement for M2. This branch
does not open, download, bind, prepare, run or score the official 1,700-example input.
It does not modify `docs/OFFICIAL_TEST_V2_FREEZE_PLAN.md`,
`experiments/official_test_v2_freeze.yaml`, any of the five frozen condition files, or
the immutable ref. Any future official-test use needs a new explicit authorization and
freeze decision after this experimental implementation is reviewed.
