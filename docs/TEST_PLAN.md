# Test Plan

Tests are proportional to risk and focus on contract enforcement.

- Unit: report search/read boundaries, calculator AST allowlist, action parsing, labels, state persistence/recovery, fixed retrieval and seed identity, hashes, sealing, and aggregate summary schemas.
- Integration: mock API/local backends, multi-step action flow, malformed JSON recovery, staged budget isolation, finalization retry, selective-review fallback, fixed-loop iterative RAG, concurrent partial-run resume, reversed completion order, multi-question state isolation, and deterministic scoring.
- Configuration: all historical configs remain loadable; all paired B-class API/local configs match method and generation settings; top-k ablations reference independent named artifacts; the planner produces 7 single-model or 14 paired rows and rejects partial/placeholder Model B groups, identical models, or frozen-input drift.
- Isolation: public-data field scan, runtime-bundle allowlist, Compose config inspection, non-overlapping networks/mounts/build contexts, no Docker socket, scorer `network_mode: none`, no exposed ports, and no gold/feedback/scorer leakage.
- Fairness: shared dataset/retrieval hashes, paired prompt and generation settings, explicit maximum budgets and actual usage, independent run IDs, no subset/scorer callback, final mode without detailed feedback, and deterministic missing/invalid handling.
- Transport: every DeepSeek mock request carries exactly `thinking.type=disabled`; missing/enabled/extended formal settings fail; Generic/Local requests omit the field; both shared client pools are explicitly 32; response tests cover stop, length, content filter, unknown finish reason, hidden-reasoning protocol drift, and aggregate counts without retaining hidden content.
- Long context: baseline traces record actual input tokens, paragraph/character counts, full assembly, local truncation, provider context errors, and configured context limit; aggregate output contains no task/error text.

Docker smoke tests verify the built image, nested B-class config paths, iterative entrypoint, the one-task nine-call M2 stateful path, and a 40-task concurrency-32 API path that seals and verifies sidecar order. They are not paid experiments and never invoke the Private Scorer. Compose expansion and image build are rerun after config or entrypoint changes.

The single final ultra audit remains historical and is not repeated. This upgrade receives a separate focused audit covering concurrency, recovery, output order, DeepSeek non-thinking transport, finish-reason/truncation behavior, and persistence leakage.
