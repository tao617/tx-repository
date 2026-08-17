# B-Class Experiment Runbook

## Status and authorization boundary

The B-class code, configuration templates, and one-/two-model plan generator are development artifacts. They do not authorize a real Model A Canary, a paid API matrix, a second-model formal run, or a `final_hidden` run. The tracked manifest has `execution_authorized: false`, and every generated plan is marked `prepared_not_executed`.

The frozen historical B0/B1/B2/B3/A0/A1/A2 matrix remains unchanged. New runs must use the B-class names and new run IDs.

The current boundary is a candidate implementation freeze, not the final experiment freeze. One development-only BITER round calibration may still follow the Model A Canary. After that calibration, freeze the selected BITER rounds, code, prompts, configs, retrieval hashes, model IDs, scorer commit, and statistical comparison rule before `dev_holdout` or `final_hidden`.

## Clean public-release preflight

Use a fresh checkout of the history-free `tao617/tx-repository` publication, or explicitly select its release branch and verify the expected commit. In the development workspace used to build this project, the local `main` branch follows upstream FinDVer rather than `origin/main`; do not use an unqualified `git switch main` there as a release-selection command.

The complete test environment includes the Gateway extra:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev,gateway]'
.venv/bin/python -m compileall -q src scripts tests
.venv/bin/pytest -q
bash -n scripts/run_agent_with_env.sh
bash -n scripts/run_stateful_mock_smoke.sh
```

The public release intentionally does not track the formal `runtime_data/public/tasks.jsonl`. Provision that Gold-free file from the approved host source, run `scripts/verify_public_data.py`, and verify its manifest SHA256 before plan preparation. For the builder-only stateful smoke, stage the tracked synthetic fixture exactly as CI does:

```bash
mkdir -p runtime_data/public
cp tests/fixtures/stateful_smoke_tasks.jsonl \
  runtime_data/public/smoke-tasks.jsonl
.venv/bin/python scripts/verify_public_data.py \
  --tasks runtime_data/public/smoke-tasks.jsonl
```

On the root-controlled WSL Docker host, expand Compose and run the mock path with the intended host user IDs. This is an infrastructure check, not an experiment:

```bash
FINDVER_UID="$(id -u)" FINDVER_GID="$(id -g)" \
  sudo -E docker compose --project-name findver-agent \
  -f deploy/wsl/docker-compose.agent.yaml --profile api config

sudo env FINDVER_UID="$(id -u)" FINDVER_GID="$(id -g)" \
  GATEWAY_DIAGNOSTICS=1 \
  scripts/run_stateful_mock_smoke.sh bclass-preflight-$(git rev-parse --short HEAD)
```

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

All paired configs use temperature 0, top-p 1, seed 7, 1024 maximum output tokens, a 32768-token prompt-construction budget, a 100000-token model context capacity, and question concurrency 32. API configs use the closed `deepseek_v4_openai` profile with `thinking.type=disabled`; Local configs use `generic_openai` and do not transmit the DeepSeek field. Runtime and Gateway each expose a bounded 32-connection shared client. The API/local method sections remain paired; transport profile, backend kind, gateway alias, timeout, and retries are backend-specific provenance.

Top-k development ablations are under `configs/bclass/ablations/` and remain scoped to one primary model on `dev_feedback`. The workspace contains the independent official `text-embedding-3-large` top-3, top-5, and top-10 outputs from frozen FinDVer commit `e8bb237def4ce555a606a45edba22666e31df248`. The gold-free Runtime artifacts preserve those upstream cutoffs rather than truncating the paragraph-ID-sorted top-10 file; top-3 SHA256 is `4c85f4cc3ea07c45ae6320032f0bad34b6f095aa8751a84f3ca0fe423e5ac8d7` and top-5 SHA256 is `78bce403b92d96858df689c15fb9afc3dd6b19a139d57b953e391ccb2f7d358d`.

The single permitted BITER calibration is `configs/bclass/ablations/BITER2_RAG10.yaml`. It changes only the fixed retrieval-round count from three to two; retrieval, finalization, generation, transport, and concurrency remain frozen.

Prepare each development extension as its own schema-v2 plan because retrieval identity is plan-level. The planner accepts only the enumerated Model-A API extensions and never overwrites an existing plan:

```bash
.venv/bin/python scripts/prepare_bclass_extension.py \
  --manifest experiments/bclass_dev_feedback_template.yaml \
  --condition RAG3_SEEDED \
  --matrix-id findver-bclass-a-devfb-top3-v1 \
  --model-a deepseek-v4-flash \
  --model-a-context-window 100000 \
  --output /secure/findver-bclass-a-devfb-top3-v1.plan.json
```

Use the same command shape with `RAG5_SEEDED` or `BITER2_RAG10` and a distinct matrix ID/output. Execute the resulting single row only through `scripts/run_bclass_plan.py`.

## Prepare a one- or two-model plan

Model A ID, backend, and context capacity are mandatory. The following preparation-only command validates seven Model A rows and freezes the current commit, task/retrieval/config hashes, prompt profile, generation settings, DeepSeek non-thinking transport, concurrency, independent run IDs, and maximum call budgets. It does not call a model. The single-model matrix ID receives a `-single-model-a` suffix.

```bash
.venv/bin/python scripts/prepare_bclass_matrix.py \
  --manifest /secure/untracked-dev-feedback-canary-manifest.yaml \
  --model-a 'deepseek-v4-flash' \
  --backend-a api \
  --model-a-context-window 100000 \
  --output /tmp/findver-bclass-model-a-plan.json
```

The Canary manifest may be untracked, but it must remain `dev_feedback`, contain only an approved Gold-free public task path, and bind that task file by SHA256. Preparation does not authorize execution.

For the later paired plan, supply the complete Model B group. Partial groups, placeholders, and an ID equal to Model A fail closed. Omitting the entire group is the only single-model form.

Before running it, require a clean tracked worktree and confirm that `runtime_data/public/tasks.jsonl` exists, contains only the public task fields, and matches the tracked manifest hash. The public release does not supply this ignored host input automatically.

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

The output path must be new; the planner never overwrites a prior plan. Verify that the schema-v2 plan has `status: prepared_not_executed`, either 7 or 14 unique run IDs, the intended commit, declared context capacity and request profile for each model, frozen concurrency 32, and the expected task/retrieval hashes. Never resume a single-model row under the paired matrix ID or copy results between their run directories.

For a later explicitly authorized 12-task Model A Canary across all seven conditions, the hard method-budget ceiling is `12 × (1+1+5+9+8+8+9) = 492` requests. Using the 100000-token context bound, the 1024-token output reserve, and the DeepSeek V4 Flash prices published on 2026-08-17 (cache-miss input USD 0.14/M, output USD 0.28/M), the absolute configured-token estimate is USD 6.96 before operational buffer. Set both a 492-call limit and a USD 8 (or CNY 60) billing limit, and re-check the [official pricing page](https://api-docs.deepseek.com/quick_start/pricing) immediately before any newly authorized run. This calculation is a guardrail, not execution authorization.

## Context capacity enforcement

`prompt_budget_tokens: 32768` bounds deterministic prompt/evidence construction; it is not the model's context window. `backend.model_context_window_tokens: 100000` is the real local capacity constraint, and the formal plan argument must exactly match the selected config. A model that cannot guarantee at least this capacity must not be placed in this matrix without a new config, focused commit, and regenerated plan.

Before transport, Runtime computes a deterministic model-independent estimate: the larger of characters divided by 4.2 and whitespace-delimited units multiplied by 1.5, plus fixed chat-message overhead. If estimated input plus the 1024-token output reserve exceeds 100000, Runtime raises an explicit context-window error without sending a request. After a successful response, provider-reported prompt tokens are authoritative and are checked against the same window. No prompt-budget or context-window extension field is sent to the OpenAI-compatible API.

The 100000 choice was checked against all 700 historical B0 request traces: actual input-token median 51185.5, p95 80561, maximum 88377. Including the 1024-token output reserve, 240 of 700 would exceed 64000, while none exceed 100000. The calibrated local estimator also produced no 100000-token overflow on those traces. This supports 100000 over 64000 for the frozen B-class templates while retaining fail-closed checks.

Every new model-request trace records prompt budget, estimated input and total tokens, model context capacity, and estimated overflow status. Successful responses record provider-reported actual input tokens. `scripts/summarize_run.py` exports only aggregate counts, means, capacity distributions, and context-error counts.

## DeepSeek request and response protocol

DeepSeek V4 thinking is enabled by default upstream, so every B-class API request uses the exact top-level structure `thinking: {type: disabled}`. This applies uniformly to one-call Baseline, every BITER retrieval/finalization call, and every Agent Exploration/Finalization/Review call because transport is centralized in the enumerated backend profile. No general request-extension dictionary exists. Gateway accepts only the disabled structure and forwards it unchanged; generic API and Local profiles omit the field.

Runtime validates `finish_reason` as `stop`, `length`, or `content_filter` and records only that value alongside visible response metadata. Unknown values fail as model responses. Non-empty hidden reasoning returned under disabled thinking raises a protocol-drift error without storing the value. Aggregate summaries report all finish-reason counts, a dedicated `length` count, and protocol drift. A length-truncated incomplete JSON action consumes the existing parse/model failure budget; do not raise one condition's output ceiling independently. Keep `max_output_tokens: 1024` until these aggregates are reviewed.

## Question concurrency and recovery

The bounded worker pool advances at most 32 different questions in one condition. Effective concurrency is `min(32, remaining tasks)`. Every phase within one question remains serial, and the existing host lock still prohibits concurrent conditions, models, or Compose projects. A fatal worker stops new assignments while already-running questions settle. Every completed prediction and metadata update is fsynced, and resume skips its ID. Partial rows may be in completion order; final predictions are atomically rebuilt in public-task order, and sealing rejects an order mismatch before constructing the ID-only evidence sidecar. Metadata and aggregate summaries record configured/effective/peak concurrency and wall-clock duration.

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
mkdir -p runtime_data/public
cp tests/fixtures/stateful_smoke_tasks.jsonl \
  runtime_data/public/smoke-tasks.jsonl
scripts/run_stateful_mock_smoke.sh bclass-stateful-mock-m2
```

The launcher rebuilds Runtime and Gateway from the current source before starting, preventing a stale `:dev` image from being reported under a newer host commit. It then drives six Exploration calls (`search -> read -> calculator` twice), a prohibited Finalization action followed by a valid draft, and a malformed Review response. The verifier requires exactly nine model calls, a Finalization protocol retry, Selective Review, verified-draft fallback, and no `weak_support` pollution from the rejected action.

### Multi-question concurrency smoke

Stage the tracked 40-task Gold-free fixture and run the separate no-credential concurrency smoke:

```bash
cp tests/fixtures/concurrent_smoke_tasks.jsonl \
  runtime_data/public/concurrent-smoke-tasks.jsonl
scripts/run_concurrent_mock_smoke.sh bclass-concurrent-mock 18081
```

The upstream asserts the disabled-thinking structure on every request. The verifier requires configured/effective concurrency 32, a peak in 2..32, 40 isolated State/Trace files, one model call per task, final task order, retained `finish_reason=stop`, no hidden-reasoning persistence, and a sealed three-file submission whose ID-only sidecar population/order match predictions.

`.github/workflows/ci.yml` runs the full no-credential test suite on Python 3.11 and 3.12, then runs both stateful and concurrent Docker paths on Python 3.12. A release commit should not be treated as publicly verified until all three jobs pass on that exact commit.

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

For every main condition and model report the configured maximum model-call budget, actual mean calls, mean input/output tokens, mean latency, wall-clock duration, configured/effective/peak concurrency, file completion, invalid and valid-output rates, staged attempts, tool/evidence counts, overall and dynamic evidence visibility, review behavior, finish-reason counts, length count, protocol drift, and termination/failure taxonomy. Accuracy and evidence-quality metrics come only from the Private Scorer aggregate output.

`file_completion_rate` is the number of prediction rows divided by expected examples and therefore includes `INVALID`. `valid_output_rate` is the strict completed-output rate; `invalid_rate` is the non-completed rate; `review_trigger_rate` is the Selective/Mandatory Review trigger rate. `prediction_coverage`, `strict_valid`, `invalid`, and `review_trigger` remain temporary compatibility aliases with those same definitions.

Select the fixed iterative-round setting against Agent mean calls using development aggregates only. Do not build an online token controller. Keep Model A and Model B tables separate until paired aggregate comparison, and record all deviations before any authorized run.
