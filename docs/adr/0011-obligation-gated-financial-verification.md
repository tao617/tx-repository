# ADR 0011: Obligation-gated financial verification Skills

- Status: Accepted
- Date: 2026-08-28

## Context

Protocol v2 records bounded evidence status, confidence, missing information and risk,
but its evidence gaps remain descriptive text authored by the model. That is useful for
prompt control but insufficient for financial verification: text does not establish a
typed dependency graph, prove that a report value came from an exact table cell, replay
an arithmetic operation, bind an accounting rule to a frozen source, or prevent a model
from claiming that a check was completed.

A proof obligation and a Skill are different. An obligation is durable Runtime state
describing what must be established and what it depends on. A Skill is a code-owned,
bounded operation that may advance a compatible obligation. Exposing every operation on
every turn would make irrelevant and high-risk capabilities available before their
inputs exist. It would also weaken the causal interpretation of Skill-use ablations.

This project needs an experimental path for typed financial proof construction without
changing the released v1/v2 behavior, the current M2 method, the sealed submission
contract, or the unexecuted Official Test V2 freeze.

## Decision

1. Add protocol v3 under the isolated `findver_agent.findoasis` package. It is enabled
   only by strict configurations whose `experimental` flag is true and whose Official
   Test, real-model and scorer-handoff authorizations are fixed false. Protocol v1 and
   v2 continue through their existing action, state, prompt and orchestration paths.
2. Represent report facts, table cells, numeric operands, unit/period checks, numeric
   operations, domain rules, rule applicability, evidence conflicts and final
   verification as typed obligations with Runtime-owned deterministic IDs, explicit
   dependencies and bounded status transitions. Model actions may propose bounded new
   obligations but cannot mark any obligation satisfied or waive a mandatory one.
3. Keep a static, immutable Registry of nine reviewed Skills. On each attempt, Runtime
   computes availability from the active obligation graph, satisfied dependencies,
   configured allowlist and budget, current evidence/value/rule candidates, frozen
   corpus validity and finalization state. Only available contracts enter the prompt.
   The always-exposed form exists solely as a named ablation and still retains hard
   precondition and target checks.
4. Add exact table-region reads and immutable `ValueRef` records. Every value binds a
   unique source span, paragraph/table coordinates, normalized Decimal value, type,
   currency, unit, scale, entity and period. Ambiguous mandatory metadata cannot unlock
   program execution.
5. Use a reference-only FinDSL AST instead of free Python or expression evaluation.
   The Runtime enforces depth/node/operand bounds, a closed operator set, Decimal
   precision 50, explicit unit/scale/currency/period rules and deterministic rounding
   and tolerance. Each successful execution emits a complete `NumericCertificate` that
   is hash-bound to its canonical program and source evidence.
6. Keep financial-rule support offline and frozen. A configured corpus must stay under
   one absolute root, pass manifest/records/source hashes, identify provenance and
   licence notes, and disable network fallback. Search returns bounded metadata; an
   explicit read persists the full record; mechanical scope, date, jurisdiction,
   predicate and conflict checks emit a `RuleApplicabilityCertificate`. The included
   corpus is synthetic test material, not production guidance.
7. Require `ClaimCertificateVerifier` before final submission. It rechecks report
   evidence and deterministically replays consumed numeric and rule certificates. A
   verified prediction or Review draft is bound to the final certificate and exact
   submission hash. Forced-finalization fallback may be incomplete only with low
   confidence and an explicit unresolved-obligation risk; integrity and contradiction
   failures remain fatal.
8. Persist v3 certificates only in per-question state, raw trace and aggregate-safe
   counters. Do not add a scorer certificate sidecar. Keep the prediction schema, the
   evidence sidecar and the deterministic three-file sealed archive unchanged. A future
   scorer contract change requires separate authorization and review.
9. Keep `docs/PROJECT_CONTRACT.md`, Official Test V2 files, all historical configs and
   M2 hashes unchanged. Do not access the 1,700 official examples, Gold, Private Scorer,
   paid models or real credentials while developing or verifying v3.

## Consequences

- Relevant Skills appear later and in smaller sets, while every accepted transition is
  attributable to a typed obligation and durable certificate.
- State is larger and validation is stricter. Resume replays ledger hashes, program
  structure, rule corpus identity, certificate envelopes and prediction bindings, so
  coherent-looking tampering fails closed.
- Numeric and rule applicability checks are deterministic, but the model still selects
  report evidence, constructs the allowlisted AST and chooses candidate rules. Those
  semantic choices remain experimental limitations rather than claims of formal proof.
- Production rule sources cannot be substituted for the synthetic corpus without
  provenance, licence, version, subject-matter review and an explicit project-contract
  amendment.
- Aggregate v3 metrics add obligation, routing, numeric, rule and local cost counts but
  never include per-question evidence or rule text.

## Rejected alternatives

- **Always expose every Skill:** increases irrelevant capability surface and obscures
  whether an operation was justified by a ready proof gap. Retained only as an ablation.
- **Add one fixed Planner model call:** consumes budget for every question, duplicates
  Runtime-verifiable routing, and makes plans non-durable unless another protocol is
  introduced.
- **Execute arbitrary Python or free expressions:** cannot provide a closed security,
  type, unit, evidence or replay boundary.
- **Retrieve rules from the live internet:** creates mutable, network-dependent sources
  with unresolved provenance, licence and prompt-injection risk.
- **Modify M2 directly:** would invalidate its frozen development comparisons and change
  the Official Test V2 candidate after the freeze.
- **Inspect official-test examples before implementation:** would violate the explicit
  authorization boundary and contaminate method development.
