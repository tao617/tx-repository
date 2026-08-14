# FinDVer Offline Verification Agent

This repository contains the public half of an isolated financial fact-verification system:

- a bounded, resumable Agent Runtime with text-JSON actions;
- the original one-call behavior retained as a comparable baseline;
- a fixed Model Gateway that alone owns the upstream model credential;
- deterministic submission sealing and a host-only handoff protocol.

The independent Private Scorer is intentionally kept outside this repository. It runs with `network_mode: none`, receives only a sealed submission archive, and never shares a container, network, mount, image, or build context with the Agent.

## Security boundary

The Agent exposes only `search_report`, `read_paragraphs`, `calculator`, and `submit_answer`. It has no browser, shell, Python execution tool, arbitrary file access, Docker socket, gold labels, scorer feedback, or scorer access. The Agent container has only an internal Docker network; only the Gateway has outbound network access, with no host port published.

Credentials are never committed or copied into images. A mode-`0600` `.env.agent` file is sourced by the controlled launcher and injected only into the Gateway. Gateway egress is direct by default; host proxy variables are deliberately not inherited.

## Start here

- [Project contract](docs/PROJECT_CONTRACT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [WSL dual-Docker runbook](docs/RUNBOOK_WSL.md)
- [Scorer protocol](docs/SCORER_PROTOCOL.md)
- [Experiment plan](docs/EXPERIMENT_PLAN.md)
- [Experiment report](docs/EXPERIMENT_REPORT.md)
- [Session recovery](docs/SESSION_HANDOFF.md)

## Quick verification

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
sudo docker compose --project-name findver-agent \
  -f deploy/wsl/docker-compose.agent.yaml --profile api config
```

Public runtime tasks must contain exactly `example_id`, `statement`, and `report`. Gold-bearing source annotations must remain in a separate private location and are transformed with `scripts/prepare_public_data.py`; they are not part of this public release.

## Experiment matrix

The supplied API and local configurations cover B0 direct, B1 chain-of-thought, B2 fixed BM25, A0 Agent without calculator, A1 full Agent, and A2 Agent with mandatory pre-submit review. `scripts/summarize_run.py` emits only aggregate efficiency metrics; accuracy is produced independently by the Private Scorer.

## Upstream benchmark

This work is based on [FinDVer: Explainable Claim Verification over Long and Hybrid-content Financial Documents](https://aclanthology.org/2024.emnlp-main.818/). The upstream benchmark authors and citation details are available from the [original FinDVer repository](https://github.com/yilunzhao/FinDVer).
