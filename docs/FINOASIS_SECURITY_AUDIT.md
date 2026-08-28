# FinOASIS Security Audit

## Audit conclusion

The Phase 8 review found no Critical or High severity issue in the FinOASIS protocol-v3
implementation. The reviewed path is suitable for the authorized experimental scope:
tracked synthetic tasks, tracked synthetic reports, a hash-bound synthetic rule corpus,
and deterministic local mocks. It is not authorized for real-model, Official Test V2,
Private Scorer, paid-provider or production-rule execution.

Audit date: 2026-08-28. Branch: `feat/findoasis-obligation-skills`. The audited Runtime
implementation is commit `e13ff6a9ba35ca3be8553697f6f91620bcfcdb7d`; Phase 8 changes
after that commit are documentation and one additional serialized-state size regression
test. The final commit and remote status are recorded in `FINOASIS_PROGRESS.md` and the
Draft PR.

## Scope and threat model

The audit covered the v3 obligation graph, strict actions, dynamic Skill resolver,
prompt boundary, report/table readers, evidence and value binding, FinDSL, frozen rule
loader and applicability evaluator, state/resume validation, final certificate replay,
aggregate metrics, Docker deployment, mock protocol, and compatibility boundaries.

Inputs from the model, report, HTML table and rule records are untrusted. The relevant
threats are hidden-Skill invocation, graph or target escape, prompt-mediated operation
injection, arbitrary code or expression execution, filesystem/network escape, numeric
confusion, corpus substitution, replay drift, state/certificate tampering, aggregate
data leakage, secret inclusion, and accidental mutation of frozen v1/v2 interfaces.

## Findings

### No arbitrary execution or generic I/O capability

- The code-owned Registry contains only the nine reviewed typed Skills. Neither report
  nor rule text can register a Skill or replace its implementation.
- FinDSL accepts a closed recursive JSON AST with reference-only leaves and a fixed
  operator enum. Raw expressions, arbitrary functions, dynamic imports, `eval`, `exec`,
  shell, subprocess, file and network primitives have no schema.
- The rule loader is local, read-only, root-confined and SHA-256 bound. Its source files
  are data, not executable modules.
- AST security tests reject dynamic execution, float arithmetic, networking, subprocess
  and arbitrary writes in the FinDSL and rule implementation modules.

### Runtime authority and dynamic gating

- Runtime owns obligation IDs, budgets, attempts, state transitions, evidence ledgers,
  Skill execution and certificates. Model control metadata cannot mark an obligation
  satisfied, waive mandatory work or supply a trusted certificate.
- Availability is recomputed from allowlist, budget, active target, dependency state and
  durable trusted inputs. A hidden or wrong-target call is rejected after the attempt is
  charged and cannot mutate proof ledgers.
- The always-exposed configuration is explicitly an ablation. It still enforces fixed
  allowlists, budgets, input readiness, target validation and transactional checks.

### Evidence, numeric and rule integrity

- Paragraph and table evidence is tied to immutable report hashes and exact context or
  cell coordinates. ValueRefs require a unique exact occurrence in already-read
  evidence; ambiguity or metadata conflict fails closed.
- Decimal arithmetic, explicit type/unit/currency/scale/period rules, AST bounds,
  zero-denominator checks and canonical certificates prevent free-expression and
  binary-float ambiguity. The final verifier re-executes the canonical program rather
  than trusting its stored result.
- The synthetic corpus binds root, manifest, records and per-rule source hashes.
  Applicability checks effective date, jurisdiction, entity scope, required document
  predicates and conflicts mechanically. The final verifier reloads and replays it.

### Persistence and replay

- State writes use a mode-0600 atomic replacement with file and directory `fsync`.
- Resume binds task, report, configuration, Registry, obligation policy and optional
  corpus identities. IDs, graph references, ledger hashes, specialist payloads,
  certificate envelopes, submission hashes and final prediction bindings are all
  revalidated.
- Schema models forbid extra fields and impose per-field and complete serialized-state
  bounds. The final Phase 8 regression verifies that individually valid bounded fields
  cannot combine into a state larger than the 4 MiB persisted envelope.

### Container and secret boundary

- Compose validation requires read-only roots, dropped capabilities,
  `no-new-privileges`, no Docker socket, no Runtime ports, only established mount
  targets, and Agent isolation behind the unchanged Gateway network path.
- Smoke scripts use an ephemeral mode-0600 environment file containing a dummy local
  token. No provider credential is required or sent. Docker remained root-controlled;
  the user was not added to the Docker group and socket permissions were not changed.
- The tracked-file scan found no `.env`, PEM/private-key file, provider key, GitHub token
  or AWS access-key pattern. The existing untracked project `.env` was not staged or
  used for a real-provider call.

### Output privacy and frozen interfaces

- Aggregate v3 output contains counts and rates only. Tests reject task IDs, claims,
  explanations, evidence text, rule text and arbitrary error strings.
- Public `Prediction`, evidence sidecar v1 and the three-member sealed archive remain
  unchanged. The Runtime bundle and a 40-prediction archive passed existing verification.
- `PROJECT_CONTRACT.md`, the Official Test V2 plan/config, M2 config, sidecar module,
  submission module and public contract schemas are byte-identical to `main`.

Frozen hashes checked during the final audit:

| Asset | SHA-256 |
|---|---|
| `docs/PROJECT_CONTRACT.md` | `1c7a4c130034727589356d00b592ad43468abe96a7023e78440a2586979239eb` |
| `docs/OFFICIAL_TEST_V2_FREEZE_PLAN.md` | `21f2b852475b1121ea67ebb3b37f771bf9fbce8ddff47227ca7e8ce360f197c0` |
| `experiments/official_test_v2_freeze.yaml` | `962a42dec60324f8f672d0059e96e790954600904bccb654ec1da6436c859a46` |
| `configs/bclass/api/M2_SELECTIVE_REVIEW.yaml` | `18556167ecdc7e216bb27580f33925f52a884bcc931feff2bb4f7b2c515f36ae` |

## Verification evidence

- Python 3.12.3: compileall passed; 530 repository tests passed in 3.78 seconds.
- Python 3.11.16: isolated `python:3.11-slim-bookworm` editable install with Git and
  repository metadata; compileall passed; 530 tests passed in 4.01 seconds. The only
  warning was the existing Starlette/httpx deprecation notice.
- Focused final security gate: 84 obligation-size, prompt, FinDSL, rule and security
  tests passed.
- Stateful M2 Docker smoke: passed with 9 mock model calls and verified Review fallback.
- Concurrent Docker smoke: 40/40 completed at peak concurrency 32; the deterministic
  three-member archive sealed and verified.
- FinOASIS Docker smoke: 4/4 synthetic tasks completed; 18/18 obligations satisfied;
  two numeric and two rule applicability certificates replayed; IE masking and mixed
  specialist-certificate composition verified.
- No real model, official input, Gold, scorer, paid API or external rule service was
  accessed.

## Residual risks and required controls

- Natural-language selection of evidence, FinDSL operands and relevant rules remains an
  experimental model responsibility. Deterministic replay proves consistency of the
  selected inputs, not that every semantically relevant input was selected.
- Document-only final certificates explicitly state `provenance_only` and
  `document_semantics_verified=false`; their internal `verified` result is a protocol-
  integrity status and is not a deterministic claim-truth assertion.
- The bundled corpus is synthetic and provides no production financial, accounting,
  legal or regulatory authority. A production corpus requires explicit authorization,
  reviewed sources, licences, version/provenance policy, domain-owner sign-off and a
  project-contract revision.
- Legacy report contexts and `html_tables` are order-aligned but lack an explicit
  foreign key. The loader validates alignment and fails closed; upstream data evolution
  must preserve or replace that invariant explicitly.
- Protocol v3 remains unauthorized for scorer handoff. Any future Official Test use
  requires a separately frozen experiment specification and authorization before data
  access, plus an explicit decision on whether the unchanged sidecar contract is
  sufficient.

No residual risk justifies weakening the current fail-closed checks or expanding the
authorized execution boundary.
