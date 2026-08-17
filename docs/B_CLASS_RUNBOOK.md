# B-Class Experiment Runbook

## Status and authorization boundary

The B-class code, configuration templates, and paired-plan generator are development artifacts. They do not authorize a paid API matrix, a second-model formal run, or a `final_hidden` run. The tracked manifest has `execution_authorized: false`, and every generated plan is marked `prepared_not_executed`.

The frozen historical B0/B1/B2/B3/A0/A1/A2 matrix remains unchanged. New runs must use the B-class names and new run IDs.

## Configuration map

The seven main conditions are paired under `configs/bclass/api/` and `configs/bclass/local/`:

| Condition | Command | Maximum calls | Purpose |
|---|---|---:|---|
| `BLC_FINDVER_COT` | `baseline` | 1 | full report, action-compatible FinDVer CoT |
| `BRAG10_FINDVER_COT` | `baseline` | 1 | frozen embedding top-10, one call |
| `BITER_RAG10` | `iterative-rag` | 5 | three fixed retrieval rounds plus two finalization attempts |
| `A_SCRATCH` | `run` | 9 | v2 full method without a seed |
| `M0_RAG10_SEEDED` | `run` | 8 | frozen top-10 seed with the v1 Agent loop |
| `M1_BUDGET_AWARE` | `run` | 8 | seeded v2 6/2/0, no review |
| `M2_SELECTIVE_REVIEW` | `run` | 9 | seeded v2 6/2/1 with selective review |

All paired configs use temperature 0, top-p 1, seed 7, 1024 maximum output tokens, a 32768-token prompt-construction budget, and a 100000-token model context capacity. The API/local pair for a condition differs only in backend kind, gateway alias, timeout, and retry settings.

Top-k development ablations are under `configs/bclass/ablations/` and remain scoped to one primary model on `dev_feedback`. The workspace contains the independent official `text-embedding-3-large` top-3, top-5, and top-10 outputs from frozen FinDVer commit `e8bb237def4ce555a606a45edba22666e31df248`. The gold-free Runtime artifacts preserve those upstream cutoffs rather than truncating the paragraph-ID-sorted top-10 file; top-3 SHA256 is `4c85f4cc3ea07c45ae6320032f0bad34b6f095aa8751a84f3ca0fe423e5ac8d7` and top-5 SHA256 is `78bce403b92d96858df689c15fb9afc3dd6b19a139d57b953e391ccb2f7d358d`.

## Prepare a paired two-model plan

Choose two explicit, different model IDs and their backend paths. This command validates all 14 paired configs and freezes the current code commit, task hash, retrieval hash, prompt profile, generation settings, config hashes, independent run IDs, and maximum call budgets. It does not call a model.

```bash
.venv/bin/python scripts/prepare_bclass_matrix.py \
  --manifest experiments/bclass_dev_feedback_template.yaml \
  --model-a 'provider/model-a' \
  --model-b 'provider/model-b' \
  --backend-a api \
  --backend-b local \
  --model-a-context-window 100000 \
  --model-b-context-window 100000 \
  --output /tmp/findver-bclass-dev-feedback-plan.json
```

The output path must be new; the planner never overwrites a prior plan. Verify that the schema-v2 plan has `status: prepared_not_executed`, 14 unique run IDs, the intended commit, declared context capacity for both models, and the expected task/retrieval hashes.

## Context capacity enforcement

`prompt_budget_tokens: 32768` bounds deterministic prompt/evidence construction; it is not the model's context window. `backend.model_context_window_tokens: 100000` is the real local capacity constraint, and the formal plan argument must exactly match the selected config. A model that cannot guarantee at least this capacity must not be placed in this matrix without a new config, focused commit, and regenerated plan.

Before transport, Runtime computes a deterministic model-independent estimate: the larger of characters divided by 4.2 and whitespace-delimited units multiplied by 1.5, plus fixed chat-message overhead. If estimated input plus the 1024-token output reserve exceeds 100000, Runtime raises an explicit context-window error without sending a request. After a successful response, provider-reported prompt tokens are authoritative and are checked against the same window. No prompt-budget or context-window extension field is sent to the OpenAI-compatible API.

The 100000 choice was checked against all 700 historical B0 request traces: actual input-token median 51185.5, p95 80561, maximum 88377. Including the 1024-token output reserve, 240 of 700 would exceed 64000, while none exceed 100000. The calibrated local estimator also produced no 100000-token overflow on those traces. This supports 100000 over 64000 for the frozen B-class templates while retaining fail-closed checks.

Every new model-request trace records prompt budget, estimated input and total tokens, model context capacity, and estimated overflow status. Successful responses record provider-reported actual input tokens. `scripts/summarize_run.py` exports only aggregate counts, means, capacity distributions, and context-error counts.

For `dev_holdout` or `final_hidden`, create a new untracked manifest with that split's task path and SHA256. Never relabel the current development file as holdout or hidden. Freeze code, prompts, retrieval files, thresholds, and configs before the single authorized `final_hidden` run.

## Builder-only Mock API and Local smoke

The deterministic mock is not an evaluation and has no gold or scorer access. In one terminal:

```bash
.venv/bin/python tests/fixtures/mock_openai_server.py --host 0.0.0.0 --port 18080
```

Create a mode-0600 temporary environment file outside the repository:

```bash
install -m 0600 /dev/null /tmp/findver-bclass-mock.env
printf '%s\n' \
  'MODEL_BASE_URL=http://host.docker.internal:18080/v1' \
  'MODEL_API_KEY=builder-mock-key' \
  'MODEL_NAME=builder-mock-upstream' \
  > /tmp/findver-bclass-mock.env
```

Run one new API-profile and one new Local-profile smoke with distinct run IDs:

```bash
scripts/run_agent_with_env.sh \
  /tmp/findver-bclass-mock.env api smoke-tasks.jsonl \
  bclass-mock-api-m2 run bclass/api/M2_SELECTIVE_REVIEW.yaml

scripts/run_agent_with_env.sh \
  /tmp/findver-bclass-mock.env local smoke-tasks.jsonl \
  bclass-mock-local-m2 run bclass/local/M2_SELECTIVE_REVIEW.yaml
```

The iterative entrypoint is exercised separately with:

```bash
scripts/run_agent_with_env.sh \
  /tmp/findver-bclass-mock.env api smoke-tasks.jsonl \
  bclass-mock-api-iterative iterative-rag bclass/api/BITER_RAG10.yaml
```

### Stateful M2 Docker smoke

The one-command stateful path uses only a fake builder key and the public smoke task:

```bash
scripts/run_stateful_mock_smoke.sh bclass-stateful-mock-m2
```

The launcher rebuilds Runtime and Gateway from the current source before starting, preventing a stale `:dev` image from being reported under a newer host commit. It then drives six Exploration calls (`search -> read -> calculator` twice), a prohibited Finalization action followed by a valid draft, and a malformed Review response. The verifier requires exactly nine model calls, a Finalization protocol retry, Selective Review, verified-draft fallback, and no `weak_support` pollution from the rejected action.

`.github/workflows/ci.yml` runs the full no-credential test suite on Python 3.11 and 3.12, then runs this stateful Docker path on Python 3.12. A release commit should not be treated as publicly verified until both jobs pass on that exact commit.

Each run must finish with `run_metadata.json` status `completed`; summarize it with:

```bash
.venv/bin/python scripts/summarize_run.py \
  --run-dir runs/bclass-mock-api-m2 \
  --output runs/bclass-mock-api-m2/efficiency-summary.json
```

## Authorized real-run command shape

After explicit authorization, use one external mode-0600 environment file per model. The environment's single `MODEL_NAME` must exactly match the model ID frozen in the paired plan. Formal B-class rows are launched only through the bound executor, never by reconstructing the generic launcher's positional arguments:

```bash
.venv/bin/python scripts/run_bclass_plan.py \
  --plan /secure/findver-bclass-dev-feedback-plan.json \
  --plan-run-id findver-bclass-dev-feedback-v1-model_a-BLC_FINDVER_COT \
  --env /secure/model-a.env

.venv/bin/python scripts/run_bclass_plan.py \
  --plan /secure/findver-bclass-dev-feedback-plan.json \
  --plan-run-id findver-bclass-dev-feedback-v1-model_a-BITER_RAG10 \
  --env /secure/model-a.env

.venv/bin/python scripts/run_bclass_plan.py \
  --plan /secure/findver-bclass-dev-feedback-plan.json \
  --plan-run-id findver-bclass-dev-feedback-v1-model_b-M2_SELECTIVE_REVIEW \
  --env /secure/model-b.env
```

The executor requires schema version 2, the frozen Git commit, a clean tracked worktree, and exact task/retrieval/config hashes. It records the effective upstream model ID and all bound provenance in Runtime metadata and the sealed manifest. Resume uses the identical command plus `--resume`; any identity change fails closed. A completed run receives an aggregate runtime summary and a new sealed three-file submission. Scorer handoff remains a later, host-only operation after Agent Compose has stopped.

## Reporting checklist

For every main condition and model report the configured maximum model-call budget, actual mean calls, mean input/output tokens, mean latency, file completion, invalid and valid-output rates, staged attempts, tool/evidence counts, overall and dynamic evidence visibility, review behavior, and termination/failure taxonomy. Accuracy and evidence-quality metrics come only from the Private Scorer aggregate output.

`file_completion_rate` is the number of prediction rows divided by expected examples and therefore includes `INVALID`. `valid_output_rate` is the strict completed-output rate; `invalid_rate` is the non-completed rate; `review_trigger_rate` is the Selective/Mandatory Review trigger rate. `prediction_coverage`, `strict_valid`, `invalid`, and `review_trigger` remain temporary compatibility aliases with those same definitions.

Select the fixed iterative-round setting against Agent mean calls using development aggregates only. Do not build an online token controller. Keep Model A and Model B tables separate until paired aggregate comparison, and record all deviations before any authorized run.
