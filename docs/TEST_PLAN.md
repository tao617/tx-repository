# Test Plan

Tests are proportional to risk and focus on contract enforcement.

- Unit: report search/read boundaries, calculator AST allowlist, action parsing, labels, state persistence/recovery, fixed retrieval and seed identity, hashes, sealing, and aggregate summary schemas.
- Integration: mock API/local backends, multi-step action flow, malformed JSON recovery, staged budget isolation, finalization retry, selective-review fallback, fixed-loop iterative RAG, concurrent partial-run resume, reversed completion order, multi-question state isolation, and deterministic scoring.
- Configuration: all historical configs remain loadable; all paired B-class API/local configs match method and generation settings; top-k ablations reference independent named artifacts; BITER2 changes only the fixed round count; M2 budget-4 changes only Exploration steps; the main planner produces 7 single-model or 14 paired rows; and the extension planner produces one hash-bound Model-A API row while rejecting condition, split, transport, retrieval, context, or frozen-input drift.
- Isolation: public-data field scan, runtime-bundle allowlist, Compose config inspection, non-overlapping networks/mounts/build contexts, no Docker socket, scorer `network_mode: none`, no exposed ports, and no gold/feedback/scorer leakage.
- Fairness: shared dataset/retrieval hashes, paired prompt and generation settings, explicit maximum budgets and actual usage, independent run IDs, no subset/scorer callback, final mode without detailed feedback, and deterministic missing/invalid handling.
- Transport: every DeepSeek mock request carries exactly `thinking.type=disabled`; missing/enabled/extended formal settings fail; Generic/Local requests omit the field; both shared client pools are explicitly 32; response tests cover stop, length, content filter, unknown finish reason, hidden-reasoning protocol drift, and aggregate counts without retaining hidden content.
- Long context: baseline traces record actual input tokens, paragraph/character counts, full assembly, local truncation, provider context errors, and configured context limit; aggregate output contains no task/error text.
- FinOASIS v3: strict obligations/actions/state/configs, conservative seeding, dynamic
  Skill gating, hidden-call rejection, exact table/value binding, bounded FinDSL Decimal
  semantics, frozen rule hash/scope/applicability, deterministic final certificate
  replay, forced incomplete controls, Review repair/fallback, resume tamper detection and
  aggregate-summary privacy.

Docker smoke tests verify the built image, nested B-class config paths, iterative
entrypoint, the one-task nine-call M2 stateful path, a 40-task concurrency-32 API path
that seals and verifies sidecar order, and a four-task FinOASIS v3 path. The v3 path
proves IE masking, ValueRef plus FinDSL, synthetic frozen-rule applicability and a mixed
final certificate while checking aggregate privacy. They are not paid experiments and
never invoke the Private Scorer. Compose expansion and image build are rerun after config
or entrypoint changes.

The historical B-class ultra audit is not repeated. FinOASIS receives its own focused
audit covering Registry/action confinement, table and corpus paths, dynamic execution/
network absence, certificate replay, backward-compatibility hashes, Docker isolation and
persistence/aggregate leakage. See `docs/FINOASIS_TESTING.md`.
