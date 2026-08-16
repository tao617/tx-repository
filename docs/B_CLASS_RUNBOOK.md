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

All paired configs use temperature 0, top-p 1, seed 7, 1024 maximum output tokens, and a 32768-token configured context limit. The API/local pair for a condition differs only in backend kind, gateway alias, timeout, and retry settings.

Top-k development ablations are under `configs/bclass/ablations/`. They are scoped to one primary model on `dev_feedback`. The current workspace contains the official top-10 artifact only. `RAG3_SEEDED` and `RAG5_SEEDED` must not run until independent official top-3 and top-5 files are supplied and validated; never derive them by truncating the paragraph-ID-sorted top-10 file.

## Prepare a paired two-model plan

Choose two explicit, different model IDs and their backend paths. This command validates all 14 paired configs and freezes the current code commit, task hash, retrieval hash, prompt profile, generation settings, config hashes, independent run IDs, and maximum call budgets. It does not call a model.

```bash
.venv/bin/python scripts/prepare_bclass_matrix.py \
  --manifest experiments/bclass_dev_feedback_template.yaml \
  --model-a 'provider/model-a' \
  --model-b 'provider/model-b' \
  --backend-a api \
  --backend-b local \
  --output /tmp/findver-bclass-dev-feedback-plan.json
```

The output path must be new; the planner never overwrites a prior plan. Verify that the plan has `status: prepared_not_executed`, 14 unique run IDs, the intended commit, and the expected task/retrieval hashes.

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

Each run must finish with `run_metadata.json` status `completed`; summarize it with:

```bash
.venv/bin/python scripts/summarize_run.py \
  --run-dir runs/bclass-mock-api-m2 \
  --output runs/bclass-mock-api-m2/efficiency-summary.json
```

## Authorized real-run command shape

After explicit authorization, use one external mode-0600 environment file per model. The environment's `MODEL_NAME` must exactly match the model ID frozen in the paired plan. Invoke the command and config recorded for each plan row; examples are:

```bash
scripts/run_agent_with_env.sh \
  /secure/model-a.env api tasks.jsonl \
  findver-bclass-dev-feedback-v1-model_a-BLC_FINDVER_COT \
  baseline bclass/api/BLC_FINDVER_COT.yaml

scripts/run_agent_with_env.sh \
  /secure/model-a.env api tasks.jsonl \
  findver-bclass-dev-feedback-v1-model_a-BITER_RAG10 \
  iterative-rag bclass/api/BITER_RAG10.yaml

scripts/run_agent_with_env.sh \
  /secure/model-b.env local tasks.jsonl \
  findver-bclass-dev-feedback-v1-model_b-M2_SELECTIVE_REVIEW \
  run bclass/local/M2_SELECTIVE_REVIEW.yaml
```

Use the task filename that corresponds to the exact task hash in the plan. Never substitute a model, task, retrieval file, config, prompt, or generation setting during resume. A completed run receives an aggregate runtime summary and a new sealed three-file submission. Scorer handoff remains a later, host-only operation after Agent Compose has stopped.

## Reporting checklist

For every main condition and model report the configured maximum model-call budget, actual mean calls, mean input/output tokens, mean latency, coverage, invalid and strict-valid rates, staged attempts, tool/evidence counts, review behavior, and termination/failure taxonomy. Accuracy and evidence-quality metrics come only from the Private Scorer aggregate output.

Select the fixed iterative-round setting against Agent mean calls using development aggregates only. Do not build an online token controller. Keep Model A and Model B tables separate until paired aggregate comparison, and record all deviations before any authorized run.
