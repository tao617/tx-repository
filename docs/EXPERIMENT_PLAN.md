# Experiment Plan

Evaluate each external API model and local small model with the same public dataset hash, model adapter, generation parameters, and deterministic scorer.

| ID | Condition | API config | Local config |
|---|---|---|---|
| B0 | one-call direct answer | `baseline_api.yaml` | `baseline_local.yaml` |
| B1 | one-call chain-of-thought prompt | `baseline_cot_api.yaml` | `baseline_cot_local.yaml` |
| B2 | one-call fixed BM25 top-10 context | `baseline_bm25_api.yaml` | `baseline_bm25_local.yaml` |
| A0 | search/read Agent without calculator | `agent_no_calculator_api.yaml` | `agent_no_calculator_local.yaml` |
| A1 | search/read/calculator Agent | `agent_api.yaml` | `agent_local.yaml` |
| A2 | A1 with mandatory pre-submit review | `agent_review_api.yaml` | `agent_review_local.yaml` |

Use `scripts/summarize_run.py` for Agent-side aggregate efficiency metrics: prediction coverage, invalid rate, mean steps, action attempts, input/output tokens, model calls, latency, and optional cost. Use only the independent Scorer summary for overall and IE/Numeric/Knowledge accuracy and coverage.

Keep capability-mode and equal-budget results separate. A2 has a larger default step ceiling because the review consumes one model turn; equal-budget comparisons must override or normalize the budget explicitly and report that choice.

Data lifecycle: iterate with detailed feedback only on `dev_feedback`; select configurations on aggregate-only `dev_holdout`; freeze code, prompt, and configuration; then run `final_hidden` once under aggregate-only scoring.
