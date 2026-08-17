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

Top-k ablations `RAG3_SEEDED`, `RAG5_SEEDED`, and `RAG10_SEEDED` are one-primary-model `dev_feedback` studies only. Each uses its independent official `text-embedding-3-large` cutoff artifact from FinDVer commit `e8bb237def4ce555a606a45edba22666e31df248`; top-3/top-5 are not derived by truncating the paragraph-ID-sorted top-10 file. The six-step M2 reference used more than four Exploration calls on 107/700 examples (15.29%), so one Model-A `M2_BUDGET4` sensitivity row is authorized. Only 39/700 examples (5.57%) entered Finalization after six Exploration calls and none reached a max-step termination, so budget 8 is not authorized. The budget-4 config changes only `exploration_steps` from 6 to 4.

### Post-freeze full-report warm-start extension

ADR 0005 authorizes implementation and offline verification, but not paid execution, of exactly one post-hoc Model-A `dev_feedback` extension named `LC_AGENT_FIRSTPASS`. It uses the `A_SCRATCH` protocol-v2 6/2/1 selective-review controller with no initial retrieval. The exact BLC full-report serialization is visible only in the first durably charged Exploration attempt, is never preloaded into the evidence ledger, and is absent from later Exploration, Finalization, and Review prompts. Transport retries within that attempt reuse the same request; any new Agent attempt does not receive the report. Final evidence IDs must still have entered the formal ledger through `read_paragraphs`.

The cleanest exploratory contrast is `LC_AGENT_FIRSTPASS` versus `A_SCRATCH`, which estimates the warm-start increment. Its comparison with `M2_SELECTIVE_REVIEW` is an operational comparison between full-report preview and pinned Top-10 seeding, not an isolated context-only effect. Its comparison with `BLC_FINDVER_COT` is a whole-system comparison. Any difference-in-differences interaction is descriptive rather than a strict factorial estimate. This extension remains outside the primary comparison and the five-test Holm family and cannot replace M2 in the current holdout protocol.

Before a separately authorized paid run, an exact-prompt offline preflight must cover all 700 tasks with zero estimated overflow against the frozen 100000-token capacity. Feasibility additionally requires 700/700 file completion, valid output at least 99 percent, zero local truncations, zero provider context errors, exactly one full-report injection per example and none in Finalization or Review, and at most 46,376,030 provider-reported input tokens. Eligibility for a separately frozen future exploratory study requires an accuracy point gain of at least 1.0 percentage point over M2, a paired-bootstrap 95 percent interval lower bound greater than -1.0 percentage point, and submitted Evidence F1 no more than 1.0 percentage point below M2.

## Pairing and frozen inputs

`scripts/prepare_bclass_matrix.py` requires Model A's explicit ID, backend, and context capacity. Model B is an all-or-nothing optional group: omitting all three fields creates seven Model A rows, while supplying all three preserves the 14-row distinct-model matrix. Placeholder Model B values and partial groups fail closed. A single-model plan receives a deterministic matrix ID distinct from the later paired plan, so result directories and resume identities cannot mix. The schema-v2 plan binds task and retrieval SHA256, per-condition prompt profile, generation settings, request profile, thinking mode, concurrency, method settings, and maximum-call budget. A new untracked `dev_feedback` Canary manifest is allowed only when its task path and SHA256 are explicit. The tracked manifest remains non-executing by design.

Formal rows use only `scripts/run_bclass_plan.py`. The executor still starts exactly one row and binds it to the effective upstream model ID, Runtime alias, clean frozen commit, config/task/retrieval hashes, backend, run ID, context capacity, request profile, thinking semantics, and configured concurrency. The same immutable identity is required on resume and copied into the sealed manifest. Generic direct launches remain builder smoke or legacy paths, not formal B-class provenance.

Initial B-class templates use temperature 0, top-p 1, seed 7, 1024 output tokens, a 32768-token prompt-construction budget, a hash-bound 100000-token model context capacity, and question concurrency 32. API rows explicitly use `deepseek_v4_openai` with `thinking.type=disabled`; Local rows use `generic_openai` without the DeepSeek field. Plan preparation and formal execution reject capacity, concurrency, profile, or thinking drift. The first iterative reference uses three retrieval rounds plus two finalization attempts. Development aggregates may determine whether a different fixed round count is closer to the Agent mean before the configuration freeze; no per-question adaptive budget or online token matching is allowed. The 1024 output limit stays fixed until finish-reason aggregates justify a protocol-wide change.

## Metrics and statistical analysis

Use `scripts/summarize_run.py` for aggregate runtime behavior: file completion, valid output, invalid, and review-trigger rates; actual model requests/responses; input/output tokens; latency; phase attempts; search/read/calculator calls; seed/dynamic paragraph counts; review fallbacks/label changes; termination reasons; failure taxonomy; configured/effective/peak concurrency and wall-clock duration; finish-reason counts including a dedicated `length` count; protocol-drift count; and long-context instrumentation. `prediction_coverage`, `strict_valid`, `invalid`, and `review_trigger` remain compatibility aliases, not primary report labels. Long-context metrics distinguish deterministic estimated input, provider-reported actual input, prompt budget, real model capacity, overflow status, and provider context errors. A `length` response with incomplete action JSON follows the unchanged parse-failure rule and is never silently accepted.

Accuracy, Evidence Precision/Recall/F1, All-Gold Evidence Recall, Initial RAG Recall, Final Agent Evidence Recall, Evidence Recovery Rate, conditional correctness, paired-bootstrap 95% intervals, and McNemar comparison belong only to the networkless Private Scorer contract in `docs/PRIVATE_EVIDENCE_METRICS.md`. The adapter is implemented in the separate Private Scorer repository at commit `37aad0d`. Before formal scoring, verify that exact or an explicitly newer frozen scorer commit in its isolated environment; never copy the implementation or its private inputs into this repository.

The holdout protocol is frozen before any `dev_holdout` score is read. `M2_SELECTIVE_REVIEW` is the sole primary candidate, `BLC_FINDVER_COT` is the sole primary comparator, and accuracy is the primary endpoint. The primary test is a two-sided exact McNemar test at alpha 0.05 with the 10,000-resample paired-bootstrap 95% interval reported as the effect estimate; there is no multiplicity adjustment for this single primary hypothesis. The five secondary method comparisons are M2 versus `BRAG10_FINDVER_COT`, calibrated `BITER2_RAG10`, `A_SCRATCH`, `M0_RAG10_SEEDED`, and `M1_BUDGET_AWARE`; their two-sided exact McNemar p-values form one Holm step-down family at familywise alpha 0.05. Top-k, budget, and BITER3-versus-BITER2 calibration results are exploratory sensitivity analyses outside the confirmatory family. Evidence metrics and all subgroup results are estimation-only and receive confidence intervals without confirmatory significance claims. This rule cannot be changed after holdout or hidden results are read.

## Data lifecycle and result placeholders

Iterate only on `dev_feedback`; select using aggregate-only `dev_holdout`; freeze code, prompt, retrieval, thresholds, configuration, and model IDs; then run `final_hidden` once under aggregate-only scoring. The current public 700-task results remain development evaluation and are not relabeled hidden.

| Split | Model A | Model B | Status |
|---|---|---|---|
| `dev_feedback` | seven main conditions, Top-3, Top-5, BITER2, and budget-4 complete; LC Agent implementation authorized but unrun | pending authorization | Existing Model A results frozen; LC extension is post-hoc and execution is unauthorized |
| `dev_holdout` | pending private split/hash | pending private split/hash | not run |
| `final_hidden` | run once after freeze | run once after freeze | not run |

No paid `LC_AGENT_FIRSTPASS`, other Model-A development extension, second-model formal, holdout, or final-hidden run is authorized by this plan. ADR 0005 authorizes only LC implementation, offline tests, checkpointing, and preparation of a non-executing hash-bound plan.

The completed BITER calibration found 75.86% accuracy at two rounds versus 76.57% at three, a paired difference of -0.71 percentage points with a 95% interval of [-2.57, +1.14]. BITER2 averaged 3.003 calls versus M2 at 3.260 and is the frozen budget-aligned fixed-loop secondary comparator. No further BITER round tuning is permitted. The completed budget-4 sensitivity averaged 3.026 calls and 81.29% accuracy versus M2 at 3.260 calls and 82.29%; it is retained as an exploratory lower-cost point. Budget 8 is not authorized. The complete comparison protocol is frozen before any aggregate-only holdout or hidden evaluation.
