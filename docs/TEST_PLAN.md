# Test Plan

Tests are proportional to risk and focus on contract enforcement.

- Unit: report search/read boundaries, calculator AST allowlist, action parsing, labels, state persistence/recovery, fixed retrieval and seed identity, hashes, sealing, and aggregate summary schemas.
- Integration: mock API/local backends, multi-step action flow, malformed JSON recovery, staged budget isolation, finalization retry, selective-review fallback, fixed-loop iterative RAG, partial-run resume, and deterministic scoring.
- Configuration: all historical configs remain loadable; all paired B-class API/local configs match method and generation settings; top-k ablations reference independent named artifacts; the two-model planner rejects identical models or frozen-input drift.
- Isolation: public-data field scan, runtime-bundle allowlist, Compose config inspection, non-overlapping networks/mounts/build contexts, no Docker socket, scorer `network_mode: none`, no exposed ports, and no gold/feedback/scorer leakage.
- Fairness: shared dataset/retrieval hashes, paired prompt and generation settings, explicit maximum budgets and actual usage, independent run IDs, no subset/scorer callback, final mode without detailed feedback, and deterministic missing/invalid handling.
- Long context: baseline traces record actual input tokens, paragraph/character counts, full assembly, local truncation, provider context errors, and configured context limit; aggregate output contains no task/error text.

Docker smoke tests verify the built image, nested B-class config paths, iterative entrypoint, and at least one Mock API and one Mock Local v2 run when Docker is available. They are not paid experiments and never invoke the Private Scorer. Compose expansion and image build are rerun after config or entrypoint changes.

The single final ultra audit occurs only after implementation, configs, tests, and documents are complete. It covers the 15 checks enumerated in `docs/B_CLASS_UPGRADE_PLAN.md` and is not repeated for speculative cleanup.

