# FinOASIS Verification Record

## Test strategy

Protocol v3 is additive, so its acceptance gate is the full repository suite plus
focused model, routing, deterministic executor, certificate, privacy, security and
container tests. No expected v1/v2 snapshot or frozen artifact hash is updated to make
v3 pass.

### Data models and resume

- deterministic obligation, ValueRef, program, rule evidence and certificate IDs;
- dependency validation and cycle rejection;
- Runtime-only satisfaction and mandatory-waiver rejection;
- strict extra-field and bounded-size validation;
- atomic save, interrupted resume and config/report/Registry/policy/corpus identity;
- complete replay validation for numeric, rule and final certificates.

### Dynamic gating

- IE questions never expose Numeric or Knowledge Skills;
- numeric execution remains hidden until two evidence-bound, metadata-complete values
  satisfy operand and unit/period dependencies;
- Knowledge Skills require a valid frozen corpus, then verified candidate and read-rule
  inputs in order;
- hidden or wrong-target calls consume attempts, record rejections and cannot mutate
  obligations or ledgers;
- the model cannot mark an obligation satisfied.

### Table, numeric and rule execution

- exact table coordinates, offsets, headers, unit/scale inference and ambiguity;
- malformed, nested, multi-root, merged and oversized table behavior;
- FinDSL success cases for arithmetic, aggregation, comparison and financial operators;
- depth/node/operand, duplicate reference, zero denominator, type, unit, currency, scale,
  period, rounding and tolerance failures;
- corpus root confinement, manifest/records/source hashes, deterministic search,
  effective dates, jurisdiction, entity scope, predicates and conflicts.

### Submission

- IE, numeric, knowledge and mixed verified final certificates;
- entailed and refuted specialist outcomes;
- deterministic program and applicability replay;
- coherent program/result/rule/envelope tampering;
- unknown or unattached evidence and whitespace explanations;
- forced-finalization incomplete controls;
- selective Review repair and certificate-bound fallback.

### Backward compatibility and privacy

- canonical v1/v2 action, state and prompt snapshots;
- M2 and Official Test V2 file/hash freezes;
- unchanged prediction, evidence-sidecar and three-member sealed archive schemas;
- aggregate summary rejection of malformed exposure/failure instrumentation;
- no task ID, statement, explanation, evidence, rule or raw error text in aggregate
  output.

## Security verification

AST-based tests inspect FinDSL and rule modules for dynamic execution, float arithmetic,
network, subprocess and arbitrary write capabilities. Additional tests cover rule-root
escape, report path confinement, immutable Registry behavior, strict action/config
schemas, malicious table inputs, excessive AST structure and state/certificate tamper.
Rule regressions also reject partial-evidence `document_not_contains` predicates and
route expired and wrong-jurisdiction search candidates through the normal Agent path to
explicit `not_applicable` certificates.
Compose tests require read-only roots, dropped capabilities, no-new-privileges, only the
existing mount targets, no Docker socket, no ports, Agent internal network only and
Gateway-only egress.

The Runtime contains no generic shell, Python, browser, file or network Skill. Report
text and synthetic rule content cannot register an operation or supply executable code.

## End-to-end fixtures

The tracked `finoasis_smoke_tasks.jsonl` contains only the three public fields and names
four tracked synthetic reports:

| Task | Required path | Negative assertion |
|---|---|---|
| IE-only | search, paragraph read, final document certificate | no Numeric or Knowledge exposure |
| Numeric | table read, two ValueRefs, greater-than FinDSL, numeric final proof | no Knowledge call |
| Knowledge | report fact, frozen rule search/read/applicability, rule final proof | no FinDSL call |
| Mixed | both specialist families followed by one final replay | final certificate contains both child certificate types |

The deterministic mock server supplies 26 strict actions. The Docker Runtime has no
provider credential and reaches only that local mock through the unchanged Gateway.

## Recorded Phase 7 gate

- Python: 3.12 locally; 3.11 and 3.12 remain configured in public CI.
- Compile: `python -m compileall -q src scripts tests` passed.
- Full suite: 529 passed in 4.05 seconds.
- Stateful M2 Docker: passed, 9 model calls, verified Review fallback.
- Concurrent Docker: 40/40 completed, peak concurrency 32, deterministic three-file
  submission sealed and verified.
- FinOASIS Docker: 4/4 completed, 18/18 obligations satisfied, two numeric programs and
  two rule applicability certificates verified, zero unavailable calls, mixed proof
  bound both child certificate families.
- Diff check: passed.
- Real model, paid API, Private Scorer, Gold and Official Test V2 inputs: not used.

Final Phase 8 results are recorded in `docs/FINOASIS_PROGRESS.md` and
`docs/SESSION_HANDOFF.md` after the last audit.

## Recorded Phase 8 gate

- Python 3.12.3: compileall passed; 530 repository tests passed in 3.78 seconds.
- Python 3.11.16: an isolated `python:3.11-slim-bookworm` editable install with Git and
  repository metadata passed compileall and all 530 tests in 4.01 seconds. Its sole
  warning was the existing Starlette/httpx deprecation notice.
- Focused final security gate: 84 tests passed.
- Frozen contracts, Official Test V2, M2, evidence-sidecar, submission and schema assets
  remained byte-identical to `main`; tracked secret scanning was clean.
- Phase 7's three Docker gates cover the same Runtime commit; Phase 8 changes only
  documentation and the serialized-state bound regression test. No production source or
  container configuration changed after those successful smokes.
- See `docs/FINOASIS_SECURITY_AUDIT.md` for scope, hashes, findings and residual risks.

## Reproduce

```bash
.venv/bin/python -m compileall -q src scripts tests
.venv/bin/pytest -q
.venv/bin/pytest -q tests/security tests/integration/test_finoasis_e2e.py
bash -n scripts/run_finoasis_mock_smoke.sh
.venv/bin/python scripts/verify_finoasis_mock_smoke.py --help
git diff --check
```

See `docs/FINOASIS_RUNBOOK.md` for root-controlled Docker commands and recovery rules.
