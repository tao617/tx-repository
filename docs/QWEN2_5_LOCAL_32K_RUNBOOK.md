# Qwen2.5 7B/14B local 32K public gate runbook

This is an independent, non-long-context public-development gate. It does not alter
the frozen 100K/B-class configurations or results and does not authorize a 700-task,
Private Scorer, holdout, or hidden run.

Both variants retain exactly the same M2 method, prompt profile, frozen embedding
Top-10 seed, and generation settings: temperature 0, top-p 1, seed 7, 1,024 output
tokens, 28,672 prompt tokens, and question concurrency 2. Both use `generic_openai`
and declare the native 32,768-token model window without YaRN or RoPE scaling.

Dedicated configurations:

- `configs/local_models/qwen2_5_7b_32k/QWEN2_5_7B_M2_32K.yaml`
- `configs/local_models/qwen2_5_14b_32k/QWEN2_5_14B_M2_32K.yaml`

Create separate mode-0600 plans for the one-example smoke and three-example Gold-free
pilot. Example for the 7B smoke:

```bash
.venv/bin/python scripts/prepare_local_model_run.py \
  --task smoke-tasks.jsonl \
  --matrix-id findver-qwen2-5-7b-32k-smoke-v1 \
  --model qwen2.5-7b-instruct \
  --model-context-window 32768 \
  --config configs/local_models/qwen2_5_7b_32k/QWEN2_5_7B_M2_32K.yaml \
  --condition-id QWEN2_5_7B_M2_32K \
  --output /secure/qwen-gates/findver-qwen2-5-7b-32k-smoke-v1.plan.json
```

Run the selected row only through `scripts/run_bclass_plan.py`. Use a distinct matrix
ID, plan, run ID, and result directory for every model and gate stage. Stop after the
first failed gate. Do not loosen the action parser, tune prompts per sample, run any
long-context condition, copy Runtime artifacts to the Private Scorer, or prepare/run
the 700-task population under this gate authorization.
