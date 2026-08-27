# FinOASIS: Obligation-Gated Financial Verification

## Status and scope

FinOASIS is the experimental protocol-v3 method in this Agent repository. It builds a
typed, evidence-bound proof state before producing the unchanged public `Prediction`.
It has been verified only with local deterministic mocks and a synthetic frozen rule
corpus. Real-model execution, Official Test V2 access and scorer handoff are explicitly
unauthorized by every tracked v3 configuration.

## Method flow (text form)

```text
public claim + named report
  -> conservative Runtime seeder
  -> typed obligation graph
  -> dynamic availability resolver
  -> prompt containing only currently available Skill contracts
  -> one strict JSON action
  -> Runtime precondition and target validation
  -> deterministic Skill execution
  -> bounded SkillResult transaction
  -> evidence/value/program/rule/certificate ledgers
  -> ClaimCertificateVerifier replay
  -> optional certificate-focused Review
  -> unchanged Prediction + aggregate-safe metrics
```

The model chooses among exposed operations and supplies bounded arguments. Runtime owns
IDs, budgets, graph transitions, exact evidence, certificate creation, replay and final
closure. Report text is always untrusted input and cannot add or redefine a Skill.

## Obligation lifecycle

Each question starts with a document-fact obligation and a final-verification obligation.
Conservative lexical signals may also seed numeric operand, unit/period, numeric
operation, domain-rule and rule-applicability obligations. The seeder sees only the
public claim; it has no subset, label, Gold or scorer input.

An obligation has one of five states:

- `pending`: no accepted progress;
- `partial`: bounded progress exists but the proof is incomplete;
- `satisfied`: Runtime accepted evidence or a verified certificate and all dependencies
  are satisfied;
- `conflicting`: accepted evidence exposes an unresolved conflict;
- `blocked`: a required dependency cannot currently advance.

Only `FinOASISQuestionState.apply_skill_result` can satisfy an obligation. Model control
may open a bounded proposal, attach already-known evidence, add a dependency, or mark
partial/conflicting state, but it has no `mark_satisfied` or mandatory-waiver operation.
IDs are deterministic and contiguous, dependency cycles are rejected, and every state
save is atomically replaced and hash-bound to task, report, config, Registry, policy and
optional rule corpus identity.

## Skill availability

The static Registry contains exactly these Skills:

| Family | Skill | Key availability condition |
|---|---|---|
| Report | `search_report` | active report-evidence obligation |
| Report | `read_paragraphs` | unread search candidate |
| Table | `read_table_region` | structurally valid relevant table candidate |
| Numeric | `bind_financial_value` | exact read evidence and numeric/unit obligation |
| Numeric | `execute_financial_program` | ready numeric-operation obligation and at least two unambiguous bound values |
| Knowledge | `search_financial_rules` | active domain-rule obligation and validated corpus |
| Knowledge | `read_financial_rules` | verified search candidate |
| Knowledge | `check_rule_applicability` | ready rule/document/scope inputs |
| Final | `submit_answer` | all mandatory dependencies satisfied, or explicit forced-finalization fallback |

Before every model attempt, Runtime intersects the Registry with the configured
allowlist, remaining per-Skill budget, active compatible obligations, satisfied
dependencies and trusted candidate state. Only that subset is serialized into the
system prompt. Calling a hidden Skill still consumes the already-charged model attempt,
records a rejection, and changes no obligation, evidence or certificate ledger.

`M3_ALL_SKILLS_ALWAYS_EXPOSED.yaml` disables only the obligation-driven masking for an
ablation. It does not bypass allowlists, budgets, corpus validation, data readiness,
target validation or transactional state checks.

## Exact table evidence and ValueRef

Report paragraph IDs retain their legacy order. Table IDs derive from the same immutable
context positions. `read_table_region` parses bounded HTML locally and persists exact
cell text, source offsets, selected coordinates, header paths, inferred unit/scale and
ambiguity flags; it never fills missing cells or guesses merged structure.

`bind_financial_value` requires a unique exact occurrence in already-read evidence. Its
immutable `ValueRef` records the source hash and coordinates plus a canonical Decimal
string, numeric type, currency, unit, scale, entity, metric and period. Deterministic
table metadata may fill an explicit `unknown`, but conflicting model metadata fails.

## FinDSL

FinDSL is a recursive JSON AST with a closed operator enum. Leaves reference an existing
`ValueRef`, a deterministically parsed `ClaimValueRef`, or one of three allowlisted
constants. Raw numeric literals and arbitrary function names are invalid.

Example: verify that 2024 revenue exceeds 2023 revenue.

```json
{
  "program": {
    "op": "greater_than",
    "args": [
      {"kind": "value_ref", "ref": "value-0001"},
      {"kind": "value_ref", "ref": "value-0002"}
    ]
  }
}
```

The executor uses Decimal precision 50 and checks AST depth (maximum 4), nodes and
operands (maximum 32), reference uniqueness, types, units, currencies, scales, periods,
denominators, rounding and tolerance. Percentage points are the internal percentage
unit; 100 basis points equal one percentage point. A successful execution stores the
canonical program and a `NumericCertificate` containing ordered operands, source
evidence, normalized snapshots, result metadata, check outcomes and claim relation.

The final verifier does not trust the stored result. It executes the stored AST again
from the current ledgers and requires exact certificate equality.

## Frozen rule example

The bundled corpus includes the synthetic rule “a public issuer recognizes revenue when
the identified performance obligation is satisfied.” A Knowledge path proceeds as:

1. `search_financial_rules` filters the validated corpus by tokens, jurisdiction and
   effective date and returns bounded candidate metadata.
2. `read_financial_rules` persists the selected full record with corpus and record hashes.
3. `check_rule_applicability` mechanically checks effective interval, jurisdiction,
   entity scope, required document predicates and explicit selected-rule conflicts.
4. A `RuleApplicabilityCertificate` records ordered rule/document references, each
   predicate outcome and one of `applicable`, `not_applicable`, or `undetermined`.

Full rule text is never included in the model prompt. `undetermined` remains partial.
During submission the certificate is recomputed from the frozen corpus and current
document evidence. The fixture is synthetic and must not be presented as guidance.

## Submission and Review

`submit_answer` targets only the final-verification obligation and cannot carry graph
deltas. `ClaimCertificateVerifier` checks:

- the active final target and every mandatory obligation;
- nonblank explanation and known submitted paragraph IDs;
- evidence ledger attachment and exact report hashes;
- required numeric/rule certificate families;
- canonical program, corpus, rule source, scope and envelope hashes;
- deterministic replay outcome versus the submitted label.

A verified submission receives a complete final certificate and may close immediately.
Selective Review is triggered by specialist certificates, non-high confidence, risk,
forced finalization or a prior verifier failure. The verified draft leaves the final
obligation pending. A Review repair receives a new certificate; parse/model/Skill
failure may fall back only to the replayed certificate-bound draft.

When forced finalization is active, low confidence plus the explicit
`unresolved_obligation` risk can produce an unchanged-schema best-effort prediction with
internal certificate status `incomplete`. Unknown evidence, tampering, label
contradiction and invalid specialist certificates are fatal and cannot use this path.

## Failure modes

| Failure | Runtime behavior |
|---|---|
| Hidden or wrong-target Skill call | attempt charged; rejection counted; no ledger mutation |
| Malformed action or extra field | strict parse failure; bounded retry within the current phase |
| Ambiguous table/value metadata | partial obligation or Skill failure; FinDSL stays hidden |
| Invalid AST/type/unit/period | no program or certificate persisted |
| Corpus path/hash/provenance mismatch | corpus load or Knowledge Skill fails closed |
| Rule scope/predicate conflict | `not_applicable` or `undetermined` certificate, never guessed |
| Certificate/envelope/result tamper | resume or final replay fails |
| Normal submit with unresolved mandatory work | `submit_answer` unavailable |
| Forced fallback without low/unresolved controls | final verification fails |
| Review failure without verified draft | invalid prediction |

## Experimental conditions and ablations

- `M3_OBLIGATION_ONLY`: report search/read plus final verification. This isolates typed
  obligations and dynamic masking from specialist Skills.
- `M3_NUMERIC`: adds table access, ValueRef and FinDSL; all Knowledge Skills and corpus
  access remain disabled.
- `M3_ALL_SKILLS_SYNTHETIC`: adds Numeric and Knowledge families using only the frozen
  synthetic corpus. This is the primary implementation/smoke condition, not a real
  financial evaluation.
- `M3_ALL_SKILLS_ALWAYS_EXPOSED`: ablation for exposure effects; never the default.

Useful later studies, after separate authorization, compare dynamic versus always
exposed routing, obligation-only versus numeric, and numeric versus all-Skills on a
development set. Production-rule and Official Test studies require additional contracts
and are not implied by these configs.

## Relationship to M2 and Official Test V2

M2 remains the frozen protocol-v2 selective-review candidate. FinOASIS neither replaces
its config nor changes its prompt/action/state snapshots. The four M3 configs live under
`configs/experimental/findoasis/` and use a separate dispatcher and state schema.

Official Test V2 remains frozen to its five protocol-v1/v2 conditions and exact existing
documents/specification. FinOASIS has not read the 1,700 official examples, created
official artifacts, executed a model, handed a submission to the Private Scorer, or
changed the Official Test V2 execution gates. Any future inclusion would require a new
prespecified experiment record and explicit authorization before input access.
