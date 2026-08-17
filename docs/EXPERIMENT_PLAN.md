# Experiment Plan

## Frozen historical matrix

The existing B0/B1/B2/B3/A0/A1/A2 API results and legacy API/local templates remain frozen development evaluation. They are not renamed, overwritten, or appended with B-class conditions.

| ID | Condition | API config | Local config |
|---|---|---|---|
| B0 | one-call direct answer | `baseline_api.yaml` | `baseline_local.yaml` |
| B1 | one-call chain-of-thought prompt | `baseline_cot_api.yaml` | `baseline_cot_local.yaml` |
| B2 | one-call fixed BM25 top-10 context | `baseline_bm25_api.yaml` | `baseline_bm25_local.yaml` |
| A0 | search/read Agent without calculator | `agent_no_calculator_api.yaml` | `agent_no_calculator_local.yaml` |
| A1 | search/read/calculator Agent | `agent_api.yaml` | `agent_local.yaml` |
| A2 | A1 with mandatory pre-submit review | `agent_review_api.yaml` | `agent_review_local.yaml` |

## B-class main matrix

New configs are isolated under `configs/bclass/api/` and `configs/bclass/local/`.

| ID | Method question | Seed | Controller/budget/review |
|---|---|---|---|
| `BLC_FINDVER_COT` | full-context FinDVer-compatible baseline | none | one call |
| `BRAG10_FINDVER_COT` | fixed-RAG reference | embedding top-10 | one call |
| `BITER_RAG10` | budget-matched fixed-loop alternative | embedding top-10 | 3 fixed rounds + 2 finalization; no controller/review |
| `A_SCRATCH` | seed contribution | none | v2 6/2/1 selective |
| `M0_RAG10_SEEDED` | seed plus legacy loop | embedding top-10 | v1 max 8 |
| `M1_BUDGET_AWARE` | staged budget/controller contribution | embedding top-10 | v2 6/2/0 no review |
| `M2_SELECTIVE_REVIEW` | complete proposed method | embedding top-10 | v2 6/2/1 selective |

Top-k ablations `RAG3_SEEDED`, `RAG5_SEEDED`, and `RAG10_SEEDED` are one-primary-model `dev_feedback` studies only. Each uses its independent official `text-embedding-3-large` cutoff artifact from FinDVer commit `e8bb237def4ce555a606a45edba22666e31df248`; top-3/top-5 are not derived by truncating the paragraph-ID-sorted top-10 file. Exploration-step ablations 4/6/8 are reserved for later development selection and are not part of implementation testing.

## Pairing and frozen inputs

`scripts/prepare_bclass_matrix.py` accepts two explicit, distinct model IDs, an explicit API/local backend, and a declared model context-window capacity for each. Its schema-v2 plan generates independent run IDs while binding both models to the same task SHA256, retrieval SHA256, per-condition prompt profile, generation settings, method settings, and maximum-call budget. The tracked manifest is `experiments/bclass_dev_feedback_template.yaml` and is non-executing by design.

Formal rows use only `scripts/run_bclass_plan.py`. The executor binds one plan row to the effective upstream model ID, Runtime alias, clean frozen commit, config/task/retrieval hashes, backend, run ID, and context capacity. The same immutable identity is required on resume and copied into the sealed manifest. Generic direct launches remain builder smoke or legacy paths, not formal B-class provenance.

Initial B-class templates use temperature 0, top-p 1, seed 7, 1024 output tokens, a 32768-token prompt-construction budget, and a hash-bound 100000-token model context capacity. Plan preparation and formal execution both reject capacity drift. The first iterative reference uses three retrieval rounds plus two finalization attempts. Development aggregates may determine whether a different fixed round count is closer to the Agent mean before the configuration freeze; no per-question adaptive budget or online token matching is allowed.

## Metrics and statistical analysis

Use `scripts/summarize_run.py` for aggregate runtime behavior: file completion, valid output, invalid, and review-trigger rates; actual model requests/responses; input/output tokens; latency; phase attempts; search/read/calculator calls; seed/dynamic paragraph counts; review fallbacks/label changes; termination reasons; failure taxonomy; and long-context instrumentation. `prediction_coverage`, `strict_valid`, `invalid`, and `review_trigger` remain compatibility aliases, not primary report labels. Long-context metrics distinguish deterministic estimated input, provider-reported actual input, prompt budget, real model capacity, overflow status, and provider context errors.

Accuracy, Evidence Precision/Recall/F1, All-Gold Evidence Recall, Initial RAG Recall, Final Agent Evidence Recall, Evidence Recovery Rate, conditional correctness, paired-bootstrap 95% intervals, and McNemar comparison belong only to the networkless Private Scorer contract in `docs/PRIVATE_EVIDENCE_METRICS.md`. The private adapter implementation is blocked while the separate scorer repository is unavailable.

## Data lifecycle and result placeholders

Iterate only on `dev_feedback`; select using aggregate-only `dev_holdout`; freeze code, prompt, retrieval, thresholds, configuration, and model IDs; then run `final_hidden` once under aggregate-only scoring. The current public 700-task results remain development evaluation and are not relabeled hidden.

| Split | Model A | Model B | Status |
|---|---|---|---|
| `dev_feedback` | pending authorization | pending authorization | templates only |
| `dev_holdout` | pending private split/hash | pending private split/hash | not run |
| `final_hidden` | run once after freeze | run once after freeze | not run |

No paid API, second-model formal, top-k ablation, budget ablation, or final-hidden run is authorized by this plan.
