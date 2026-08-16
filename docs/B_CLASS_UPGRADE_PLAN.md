# B-Class Upgrade Plan

## Authority and objective

This document is the single source of truth for the B-class conference upgrade. Authority is resolved in this order:

1. `docs/PROJECT_CONTRACT.md`
2. accepted ADRs in `docs/adr/`
3. this plan
4. `docs/STATE.yaml`
5. `docs/SESSION_HANDOFF.md`
6. chat context

The target method is a **RAG-Seeded Budget-Aware Evidence Verification Agent** that preserves the original one-call FinDVer baseline and the frozen B0/B1/B2/B3/A0/A1/A2 experiment history.

The fixed method flow is:

```text
frozen FinDVer retrieval seed
  -> structured evidence-sufficiency control
  -> gap-directed search/read/calculation
  -> budget-aware adaptive stop
  -> independently reserved finalization
  -> deterministic selective-review gate
  -> verified-draft fallback on review failure
```

The implementation must test whether a fixed RAG result is a useful seed, whether dynamic evidence recovery improves it, whether the gain survives a budget-matched iterative-RAG comparison, and whether reserved finalization plus selective review improves valid-output coverage.

## Invariants

- Runtime and Private Scorer remain isolated by build context, Compose project, network, and mounts.
- Runtime receives no gold, subset, explanation, relevant context, scorer output, or builder feedback.
- Runtime exposes only `search_report`, `read_paragraphs`, `calculator`, and `submit_answer`.
- Fixed retrieval is initialization data, not a new skill, model call, exploration step, search call, or read call.
- Reports remain fully searchable after seed initialization.
- Sealed submissions continue to contain exactly `predictions.jsonl`, `manifest.json`, and `SHA256SUMS`.
- Historical configurations, archived submissions, reports, and formal results are immutable.
- No paid formal matrix or second-model run is authorized by this upgrade.

## Method and compatibility decisions

### Fixed retrieval and seed

`FixedRetrievalIndex` is the general retrieval loader. `FixedEmbeddingIndex` remains as a compatibility alias. The loader accepts both the original FinDVer list format and the current metadata-wrapped format. Supported retrievers are `bm25`, `text-embedding-3-large`, and `contriever-msmarco`; supported cutoffs are 3, 5, and 10.

List-format files require explicit configured `retriever` and `top_k`. Wrapped files must agree with configured metadata. Every load validates unique non-empty IDs, safe report filenames, unique non-negative paragraph IDs, report bounds, `len(retrieved_context) <= top_k`, recursive forbidden fields, and report consistency. The exact file SHA256, retriever, cutoff, and seeded paragraph IDs are persisted and must match on resume.

Top-3 and Top-5 files are independent frozen retrieval artifacts. They must not be derived by truncating paragraph-ID-reordered Top-10 files. They may be produced only from official cutoff-specific files or scored `retrieved_paragraphs` source data.

Seeded evidence is pinned with source `fixed_rag:<retriever>:top<k>` and selection reason `seeded by frozen upstream retrieval`. It counts toward evidence size, unique paragraphs, prompt tokens, and paragraph-efficiency metrics, but not tool or model budgets.

### Protocol versions and budgets

Protocol v1 keeps the historical `max_steps` behavior. Protocol v2 uses independent budgets:

```yaml
agent:
  protocol_version: v2
  exploration_steps: 6
  finalization_steps: 2
  review_steps: 1
  review_policy: selective
```

The v2 phases are `initialization`, `exploration`, `finalization`, `review`, and `closed`. Exploration errors consume only exploration attempts. Finalization errors consume only finalization attempts, and only `submit_answer` is allowed there. Review errors consume only review attempts. Exhausting exploration always transfers to reserved finalization; an invalid prediction is permitted only when all finalization attempts are exhausted without any verified draft.

Question state is versioned and persists protocol version, phase counters, initial-retrieval state, structured evidence status, risk flags, verified draft fields, review trigger/fallback metadata, phase-specific failure counters, and termination reason. Existing v1 state remains readable; incompatible v2 retrieval-resume metadata fails closed.

### Evidence sufficiency

Protocol v2 actions include a bounded `control` object with:

- `evidence_status`: `none`, `partial`, `sufficient`, or `conflicting`;
- up to five bounded `missing_information` strings;
- `confidence`: `low`, `medium`, or `high`;
- enumerated `risk_flags`: `calculation`, `conflicting_evidence`, `weak_support`, `retrieval_gap`, or `table_alignment`.

The controller is part of the existing action response. It creates no skill and no judge-model call, and stores no chain-of-thought. Missing information synchronizes to `open_questions`. A `sufficient` status followed by unrelated exploration is a recoverable exploration protocol error.

### Finalization and review

The first valid `submit_answer` is fully validated through `SubmitAnswerSkill` before becoming a draft. Review policy is `none`, `mandatory`, or `selective`. Selective review uses deterministic triggers: calculator use, conflicting evidence, low draft confidence, forced finalization without sufficient evidence, weak support, or table-alignment risk.

Review can replace a verified draft only with another valid submission. A model, parse, protocol, skill, or budget failure during review falls back to the verified draft and records the failure and changed label/evidence/explanation flags.

### Baselines and prompts

The baseline prompt registry retains current profiles and adds `findver_direct_json` and `findver_cot_json`. CoT means internal stepwise checking; every primary experiment still returns the shared strict JSON action schema and never exposes long-form reasoning.

The budget-matched iterative-RAG baseline is a non-agent fixed loop: common fixed seed, configured fixed query-generation/read rounds, then strict finalization. It has no evidence controller, adaptive stop, or review, and does not vary its number of rounds per question.

## Configuration fields

### Agent v2

```yaml
agent:
  protocol_version: v2
  exploration_steps: 6
  finalization_steps: 2
  review_steps: 1
  review_policy: selective
  initial_retrieval:
    enabled: true
    retrieval_file: /runtime_data/retrieval/embedding_top10.json
    retriever: text-embedding-3-large
    top_k: 10
    preload_as_evidence: true
```

When retrieval is disabled, `retrieval_file`, `retriever`, and `top_k` are unnecessary. Historical top-level and agent `max_steps` configurations retain their existing meaning under v1.

### Iterative RAG

```yaml
mode: iterative_rag
iterative_rag:
  retrieval_rounds: 3
  results_per_round: 5
  auto_read_per_round: 5
  finalization_steps: 2
```

Model names remain configuration values. The experiment-matrix launcher accepts two explicit, distinct model IDs and binds both to identical task hash, retrieval hash, prompt profile, and generation settings while producing separate run IDs.

## Experiment matrix

New configurations live under `configs/bclass/`; they do not alter historical IDs.

| ID | Method | Seed | Controller | Budget | Review |
|---|---|---|---|---|---|
| `BLC_FINDVER_COT` | full-context one-call baseline | none | none | one call | none |
| `BRAG10_FINDVER_COT` | fixed embedding RAG one-call baseline | top-10 | none | one call | none |
| `BITER_RAG10` | fixed-loop iterative RAG | top-10 | none | fixed rounds + finalization | none |
| `A_SCRATCH` | v2 agent from scratch | none | structured | staged | selective |
| `M0_RAG10_SEEDED` | seeded legacy agent loop | top-10 | legacy | v1 | legacy-compatible |
| `M1_BUDGET_AWARE` | full v2 agent | top-10 | structured | 6/2/0 | none |
| `M2_SELECTIVE_REVIEW` | full v2 method | top-10 | structured | 6/2/1 | selective |

Top-k development ablations are `RAG3_SEEDED`, `RAG5_SEEDED`, and `RAG10_SEEDED` under `configs/bclass/ablations/`. They are planned for one primary model on development data only. Exploration-budget ablations reserve 4, 6, and 8 steps but are not run during implementation.

Every new run uses a new run ID, data manifest, code commit, config hash, and retrieval-file hash. Model A and Model B result slots are documentation placeholders until explicitly authorized runs occur.

## Metrics and scorer contract

Agent-side aggregate summaries report coverage, invalid and strict-valid rates, mean model calls/tokens/latency, phase attempts, tool calls, seed and dynamic paragraph counts, review trigger/fallback/change counts, termination reasons, and parse/model/skill errors by phase.

Long-context instrumentation records actual baseline input tokens, report paragraph count, report character count, whether the report was fully assembled, local truncation, provider context errors, and configured model context limit. Offline analysis reserves short/medium/long document and front/middle/back evidence-position groups.

Private scorer analysis owns Evidence Precision/Recall/F1, All-Gold Evidence Recall, Initial RAG Recall, Final Agent Evidence Recall, Evidence Recovery Rate, correctness conditioned on initial/recovered evidence, paired-bootstrap 95% confidence intervals, and McNemar comparison. Only aggregate outputs may cross the scorer boundary. If the private scorer is unavailable in this workspace, only the contract and adapter schema are implemented here and the private implementation remains explicitly blocked.

## Implementation phases

| Phase | Deliverable | Verification | Status |
|---|---|---|---|
| 0 | recovery, frozen baseline confirmation, this plan, comprehensive ADR | full pytest | complete |
| 1 | generalized fixed retrieval and idempotent RAG seed | targeted retrieval/seed tests + full pytest | complete |
| 2 | v2 phase state machine and reliable finalization | targeted state/budget/resume tests + full pytest | complete |
| 3 | evidence control, prompts, selective review, verified fallback | targeted action/prompt/review tests + full pytest | complete |
| 4 | iterative-RAG runner, aggregate metrics, scorer-side contract | targeted runner/summary/contract tests + full pytest | complete |
| 5 | B-class configs, two-model matrix preparation, manifests and runbook | config/CLI/mock API+local tests + full pytest | complete |
| 6 | one final security, compatibility, configuration, and regression audit | prescribed audit + full pytest | complete |

Each completed phase runs `scripts/context_checkpoint.py`, updates this status table, and receives one focused commit.

## Completed items

- Recovered the repository at `c3e9ebbcd5563f8bbc25cfac248d5931326f19ca` with a clean worktree.
- Read the project contract, accepted ADR, state, handoff, experiment plan, and test plan.
- Confirmed the historical seven-condition formal API matrix is documented as frozen development evaluation.
- Established an 81-test passing baseline using the repository virtual environment.
- Recorded the upgrade method and compatibility decisions in ADR 0002 and this plan.
- Generalized fixed retrieval across supported retrievers and top-3/top-5/top-10, with list/wrapped formats, recursive leakage checks, strict metadata validation, and artifact SHA256 identity.
- Added optional, pinned, budget-free, prompt-visible RAG Seed initialization with idempotent hash-bound resume and continued whole-report access.
- Added protocol v2 with durable initialization/exploration/finalization/review/closed phases and independent attempt/error counters, while preserving the v1 max-steps path.
- Reserved strict submit-only Finalization attempts, including format repair, phase-bound resume validation, explicit termination reasons, and INVALID only after Finalization exhaustion.
- Added bounded v2 evidence status, confidence, missing-information, and enumerated risk control; state and prompts retain only operational evidence gaps rather than chain-of-thought.
- Added FinDVer Direct/CoT JSON profiles, deterministic selective-review triggers, verified-draft validation, review change metadata, and failure-safe fallback for v2 and compatible mandatory review.
- Added a fixed-loop iterative-RAG runner with the common frozen seed, fixed query/search/auto-read rounds, strict submit-only finalization, explicit maximum-call trace metadata, and no controller, adaptive stop, or review.
- Expanded the aggregate-only run summary with strict validity, actual request/response usage, staged attempts, tool/evidence/review metrics, termination/failure taxonomy, and long-context instrumentation.
- Defined private evidence/recovery/conditional-correctness metrics plus aggregate paired-bootstrap and McNemar schemas; the absent separate Private Scorer implementation is explicitly blocked.
- Added paired API/Local configs for all seven B-class conditions plus independent-file Top-3/5/10 development ablations, without modifying historical configs.
- Added a non-executing two-model matrix planner that requires distinct explicit model IDs and freezes paired task/retrieval hashes, prompt profiles, generation settings, config hashes, budgets, and run IDs.
- Added the B-class manifest/runbook and updated experiment/test/README guidance; rebuilt Runtime/Gateway images and completed Mock API, Mock Local, and iterative-entry container smokes without paid calls.
- Completed the single final ultra audit across all 15 prescribed leakage, isolation, submission, history, seed, budget, review, state, iterative-baseline, config, mock, Compose, and regression checks; recorded evidence in `docs/B_CLASS_FINAL_AUDIT.md`.

## Pending items

- Real private-scorer metric implementation, if the separate scorer repository is not available.
- Independent official top-3 and top-5 retrieval artifacts required for those development ablations.
- Any paid API, final-hidden, full second-model, top-k ablation, or budget-ablation run.

## Out of scope

No multi-agent runtime, planner/verifier model, web or SEC retrieval, vector database, training, reinforcement learning, complex claim graph, cross-question memory, prompt-mutating meta-agent, large synthetic long-context study, broad table-serialization study, leaderboard reproduction, unauthorized paid run, random label guessing, or gold-informed runtime control will be added. Potential extensions may be listed only as future work.
