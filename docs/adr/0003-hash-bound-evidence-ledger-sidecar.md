# ADR 0003: Hash-bound ID-only evidence-ledger sidecar

- Status: Accepted
- Date: 2026-08-16

## Context

Private evidence recovery metrics require the frozen initial RAG set and the final Agent evidence ledger for every example. The sealed three-file submission deliberately excludes state and traces, so the networkless Private Scorer cannot derive those sets from `predictions.jsonl`. Moving Gold or scorer logic into Runtime is prohibited, while redefining final-ledger recall as submitted-evidence recall would remove the intended distinction between evidence found and evidence cited.

The user explicitly authorized a narrow project-contract change permitting one additional paragraph-ID-only sidecar.

## Decision

Keep the sealed submission archive unchanged at exactly three members. After an Agent run completes, the trusted WSL host deterministically extracts only:

- `example_id`;
- `initial_rag_evidence_ids`;
- `final_agent_evidence_ids`.

The host writes those records to `evidence-ledger.jsonl`. The file is schema-validated, population- and order-checked against the predictions, made mode `0444`, and its SHA256 plus schema version are written into the sealed submission manifest. Handoff verifies the archive and sidecar together, copies both only after Agent and Scorer projects have stopped, and verifies the copied sidecar hash.

The sidecar may not contain report or statement text, labels, predictions, explanations, source names, reasons, risk fields, calculations, prompts, traces, Gold, feedback, scorer data, or arbitrary state. A missing, extra, malformed, population-mismatched, or hash-mismatched sidecar fails closed.

Legacy and non-Agent submissions may omit the sidecar. The archive continues to contain only `predictions.jsonl`, `manifest.json`, and `SHA256SUMS`.

## Consequences

- The Private Scorer can compute initial-retrieval recall, final-ledger recall, and evidence recovery without receiving text or Runtime state.
- The archive protocol remains three-file and existing legacy manifests remain readable.
- Agent sealing now requires a complete persisted state population.
- The sidecar and archive form one logical scorer input; neither is sufficient for final-ledger analysis by itself.

## Rejected alternatives

- Put the full state or trace in the archive: leaks unnecessary Runtime material.
- Add paragraph text to the sidecar: unnecessary for ID-based private metrics.
- Reuse only submitted evidence IDs: cannot measure evidence found but not cited.
- Let Runtime access Gold or compute recovery metrics: violates the scorer boundary.
