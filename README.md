# FinDVer Offline Verification Agent

This repository contains the public half of an isolated financial fact-verification system:

- a RAG-seeded, budget-aware, resumable evidence-verification Agent;
- independently reserved exploration, finalization, and selective-review phases;
- the original one-call behavior and a fixed-loop budget-matched iterative-RAG baseline;
- a fixed Model Gateway that alone owns the upstream model credential;
- deterministic submission sealing and a host-only handoff protocol.

An additive experimental protocol v3, FinOASIS, is also implemented behind strict
mock-only configurations. It uses typed proof obligations, dynamic Skill masking,
evidence-bound table values, a Decimal-only FinDSL, a frozen synthetic rule corpus and
deterministic final certificate replay. It has not been run with a real model, Official
Test V2 input or the Private Scorer.

The independent Private Scorer is intentionally kept outside this repository. It runs with `network_mode: none`, receives only a sealed submission archive, and never shares a container, network, mount, image, or build context with the Agent.

## Security boundary

Protocols v1/v2 expose only `search_report`, `read_paragraphs`, `calculator`, and
`submit_answer`. Experimental v3 replaces that fixed action surface with a code-owned
nine-Skill Registry and exposes only the dynamically available subset for the current
typed obligation. Its FinDSL is a reference-only AST, not Python or a generic calculator;
its rule loader is local, frozen and networkless. No protocol has a browser, shell,
arbitrary file access, Docker socket, Gold labels, scorer feedback or scorer access. The
Agent container has only an internal Docker network; only the Gateway has outbound
network access, with no host port published.

Credentials are never committed or copied into images. A mode-`0600` `.env.agent` file is sourced by the controlled launcher and injected only into the Gateway. Gateway egress is direct by default; host proxy variables are deliberately not inherited.

## Start here

- [Project contract](docs/PROJECT_CONTRACT.md)
- [B-class upgrade plan](docs/B_CLASS_UPGRADE_PLAN.md)
- [B-class experiment runbook](docs/B_CLASS_RUNBOOK.md)
- [Architecture](docs/ARCHITECTURE.md)
- [FinOASIS method](docs/FINOASIS_METHOD.md)
- [FinOASIS experimental runbook](docs/FINOASIS_RUNBOOK.md)
- [FinOASIS verification record](docs/FINOASIS_TESTING.md)
- [WSL dual-Docker runbook](docs/RUNBOOK_WSL.md)
- [Scorer protocol](docs/SCORER_PROTOCOL.md)
- [Private evidence metric contract](docs/PRIVATE_EVIDENCE_METRICS.md)
- [Experiment plan](docs/EXPERIMENT_PLAN.md)
- [Experiment report](docs/EXPERIMENT_REPORT.md)
- [Model A B-class development results](docs/B_CLASS_MODEL_A_DEV_FEEDBACK_REPORT.md)
- [Qwen Model-B development results](docs/B_CLASS_QWEN_MODEL_B_DEV_FEEDBACK_REPORT.md)
- [Session recovery](docs/SESSION_HANDOFF.md)

## Latest Qwen Model-B results

The frozen Qwen3.5-27B parity run completed 11 conditions with 700
`dev_feedback` examples per condition. These are aggregate development results,
not holdout, hidden-set, leaderboard, or production claims.

| Operating point | Accuracy | Valid output | Mean model calls | Same-condition Model A |
|---|---:|---:|---:|---:|
| `M2_SELECTIVE_REVIEW` | **81.71%** | 99.86% | 2.996 | 82.29% |
| `M1_BUDGET_AWARE` | 81.29% | 99.86% | 2.546 | 79.71% |
| `M2_BUDGET4` | 81.14% | 99.71% | 2.749 | 81.29% |

Qwen M2 differs from Model A M2 by -0.57 percentage points, with paired 95%
CI [-3.43, +2.29] and exact p=0.772989. The one-call Qwen BLC and BRAG10 rows
had substantial failed model responses and are retained as transport-degraded
observations. See the [full 11-condition report](docs/B_CLASS_QWEN_MODEL_B_DEV_FEEDBACK_REPORT.md)
for runtime cost, paired comparisons, evidence metrics, and limitations.

## Quick verification

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
sudo docker compose --project-name findver-agent \
  -f deploy/wsl/docker-compose.agent.yaml --profile api config
```

Public runtime tasks must contain exactly `example_id`, `statement`, and `report`. Gold-bearing source annotations must remain in a separate private location and are transformed with `scripts/prepare_public_data.py`; they are not part of this public release.

Credential-free FinOASIS verification uses four tracked synthetic tasks and reports:

```bash
install -m 0644 tests/fixtures/finoasis_smoke_tasks.jsonl \
  runtime_data/public/finoasis-smoke-tasks.jsonl
sudo env FINDVER_UID="$(id -u)" FINDVER_GID="$(id -g)" \
  scripts/run_finoasis_mock_smoke.sh finoasis-v3-smoke 18082
```

The four configs under `configs/experimental/findoasis/` fix Official Test, real-model
and scorer-handoff authorization to false. The always-exposed config is an ablation,
not a default method.

## Experiment matrices

The historical B0/B1/B2/B3/A0/A1/A2 configs and results remain frozen development evaluation. New API/local B-class configs live only under `configs/bclass/` and cover full-context and fixed-RAG baselines, fixed-loop iterative RAG, scratch and seeded Agents, staged finalization, and selective review.

Prepare a non-executing paired plan for two explicit, distinct models with:

```bash
.venv/bin/python scripts/prepare_bclass_matrix.py \
  --manifest experiments/bclass_dev_feedback_template.yaml \
  --model-a 'provider/model-a' --model-b 'provider/model-b' \
  --backend-a api --backend-b local \
  --output /tmp/findver-bclass-plan.json
```

This command validates and freezes inputs but does not call a model. No paid matrix or final-hidden run is authorized. See the B-class runbook for Mock API/Local smoke commands and the exact later execution shape.

`scripts/summarize_run.py` emits aggregate-only runtime metrics. For v3 it adds typed
obligation, Skill exposure/call/rejection, numeric, rule and local-cost aggregates
without copying per-question evidence or rule text. Accuracy and evidence-quality/
statistical comparisons are produced independently by the Private Scorer; a certificate
sidecar and v3 scorer handoff remain unauthorized.

## Upstream benchmark

This work is based on [FinDVer: Explainable Claim Verification over Long and Hybrid-content Financial Documents](https://aclanthology.org/2024.emnlp-main.818/). The upstream benchmark authors and citation details are available from the [original FinDVer repository](https://github.com/yilunzhao/FinDVer).
