# Concurrency, Thinking, and Truncation Focused Audit

- Date: 2026-08-17
- Scope: single-model planning, question concurrency/recovery/order, DeepSeek V4 non-thinking transport, finish-reason/truncation handling, and persistence boundaries
- Classification: focused post-upgrade audit; this is not a repeat of the historical B-class ultra audit
- Real-model execution: none
- Private Scorer execution: none

## Findings

1. The schema-v2 planner produces seven unique Model A rows when the complete Model B group is omitted and preserves fourteen unique rows when the group is supplied. The single-model matrix ID is distinct from the paired ID. Partial groups, placeholders, duplicate IDs, and model/config/task/retrieval/commit/context/profile/concurrency drift fail closed. The executor still launches exactly one selected row.
2. All tracked run configs freeze question concurrency at 32 and retain the validation ceiling of 32. The worker pool uses `min(configured, remaining)`, never overlaps phases inside a question, stops new assignments after the first fatal worker error, settles in-flight work, and durably journals every completion. Resume skips completed IDs.
3. Partial predictions may reflect completion order. Final predictions are atomically reconstructed in public-task order. Sealing now rejects prediction-order drift before creating the ID-only evidence sidecar; both archive and sidecar order were verified on the 40-task Docker smoke.
4. Runtime and Gateway shared HTTP clients both expose explicit 32-connection limits. The existing global evaluation lock and one-Compose-project launcher behavior remain unchanged, so this upgrade does not authorize concurrent conditions, models, or projects.
5. B-class API configs use only `deepseek_v4_openai` with `thinking.type=disabled`; Local configs use `generic_openai` without that field. Gateway accepts and forwards only the exact disabled structure. No general request-extension dictionary was added. The stateful upstream asserted the field on all nine Exploration/Finalization/Review requests, and the concurrent upstream asserted it on all forty requests.
6. Runtime accepts only `stop`, `length`, and `content_filter` finish reasons. Traces retain the reason without hidden reasoning, summaries count every reason and expose a dedicated length count, and incomplete length-truncated JSON follows the existing parse-failure rule. Unknown reasons fail closed.
7. A non-empty hidden-reasoning response under disabled thinking becomes a bounded `protocol_drift` error. Directed persistence tests found neither the hidden value nor its response field in Trace, State, Runtime metadata, predictions, or the sealed archive.
8. The rebuilt Runtime image contains only the allowlisted application/config/contract files. File-name and exact-marker scans found no Gold/scorer/feedback/secret payload, mock key, or generic request-extension field. The detector necessarily names the upstream hidden-reasoning response field in source code, but no response value is retained.

## Verification evidence

- Pre-change baseline: 188 tests passed with one existing Starlette warning.
- Final directed acceptance suite: 81 tests passed with the same warning.
- Full post-upgrade suite: 225 tests passed with the same warning.
- Runtime and Gateway images rebuilt from their separate allowlisted contexts. One transient BuildKit parent-snapshot export failure cleared on an unchanged retry.
- Stateful M2 Docker smoke: 8 actions, 9 model calls, `review_fallback`.
- Concurrent Docker smoke `upgrade-concurrent-20260817-03`: 40/40 completed, configured/effective/peak concurrency 32/32/32, wall-clock 3.019598 seconds, 40 `stop`, zero `length`, zero protocol drift, sealed archive and evidence sidecar verified.
- Preparation-only Model A plan: schema v2, `prepared_not_executed`, one model, seven unique rows, matrix `findver-bclass-dev-feedback-v1-single-model-a`, DeepSeek profile disabled, concurrency 32.

The first two concurrent smoke IDs were host-verifier diagnostics after Runtime completed: `-01` used root Python without the repository package, and `-02` hit Git ownership protection during sealing. The final script uses the repository environment when available and process-scoped `safe.directory`; no global Git setting changed. All diagnostic runs, mock submissions, staged tasks, and generated plans are removed after verification.

## Authorization boundary

No credential file was created beyond short-lived fake-key `/tmp` files deleted by trap. No real model was probed, no real API request was sent, and no Canary, paid matrix, Model B, `dev_holdout`, or `final_hidden` execution occurred. Those operations remain blocked pending new explicit user authorization.
