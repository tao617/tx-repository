# Local DeepSeek R1 Distill 8B public-development runbook

This path is an independent local-model experiment. It does not alter or reuse the
frozen 100K B-class local configurations and does not authorize `dev_holdout`,
`final_hidden`, Private Scorer access, or scorer handoff.

The dedicated configuration is
`configs/local_models/deepseek_r1_distill_llama_8b_32k/M2_SELECTIVE_REVIEW_32K.yaml`.
It retains the M2 6/2/1 selective-review controller and frozen embedding Top-10 seed,
uses `generic_openai`, declares the actual 32,768-token model window, reserves 1,024
tokens for output, caps prompt construction at 28,672 tokens, and starts with two
question workers for two single-GPU replicas.

Create one external mode-0600 plan per public task population. Plans are immutable,
task-hash-bound, config-hash-bound, commit-bound, and explicitly record that scorer
handoff and holdout/hidden execution are unauthorized:

```bash
.venv/bin/python scripts/prepare_local_model_run.py \
  --task smoke-tasks.jsonl \
  --matrix-id findver-local-r1-8b-32k-smoke-v1 \
  --model deepseek-r1-distill-8b \
  --model-context-window 32768 \
  --output /secure/findver-local-r1-8b-32k-smoke-v1.plan.json
```

Execute a selected row only through the hash-bound executor:

```bash
.venv/bin/python scripts/run_bclass_plan.py \
  --plan /secure/findver-local-r1-8b-32k-smoke-v1.plan.json \
  --plan-run-id \
    findver-local-r1-8b-32k-smoke-v1-model_local-M2_SELECTIVE_REVIEW_32K \
  --env /secure/deepseek-r1-8b.env
```

Use distinct matrix IDs and plan paths for the one-example smoke, three-example
Gold-free pilot, and 700-example public development run. Keep method and generation
settings identical across those stages. The executor automatically runs the standard
summary, seal, and archive verification after Runtime completion. Do not invoke the
handoff script for this experiment without separate authorization.
