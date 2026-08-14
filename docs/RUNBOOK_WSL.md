# WSL Dual-Docker Runbook

This runbook assumes Ubuntu 24.04 under WSL, the Agent repository at `/home/taoxi/project/first`, and the independent Private Scorer at `/home/taoxi/secure/FinDVer-Scorer-Private`.

Docker remains root-controlled. Do not add the interactive user to the `docker` group because that group is root-equivalent.

## 1. Recover and test

```bash
cd /home/taoxi/project/first
git status --short
git log --oneline -10
cat AGENTS.md docs/PROJECT_CONTRACT.md docs/STATE.yaml docs/SESSION_HANDOFF.md
.venv/bin/pytest -q
```

If Docker is absent:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2 docker-buildx
sudo systemctl enable --now docker
```

`deploy/wsl/docker-daemon.local.example.json` documents the optional `mirror.gcr.io` Docker Hub pull-through cache. Install it as `/etc/docker/daemon.json` only when base-image pulls need it, then restart Docker.

## 2. Prepare public and private data

Gold-bearing source data must stay outside the Agent repository. The Agent input contains only `example_id`, `statement`, and `report`; private gold stays outside this repository with mode `0600`.

```bash
cd /home/taoxi/project/first
.venv/bin/python scripts/prepare_public_data.py \
  --source /home/taoxi/secure/FinDVer-Source/testmini.json \
  --public-tasks runtime_data/public/tasks.jsonl \
  --private-gold /home/taoxi/secure/FinDVer-Scorer-Private/private/gold.jsonl
.venv/bin/python scripts/verify_public_data.py \
  --tasks runtime_data/public/tasks.jsonl
chmod 0600 /home/taoxi/secure/FinDVer-Scorer-Private/private/gold.jsonl
```

Never copy private gold, scorer output, feedback, or credentials into the Agent repository, image, prompt, trace, or state.

## 3. Build the Agent and Gateway

```bash
cd /home/taoxi/project/first
sudo docker compose --project-name findver-agent \
  -f deploy/wsl/docker-compose.agent.yaml --profile api build
sudo docker compose --project-name findver-agent \
  -f deploy/wsl/docker-compose.agent.yaml --profile api config
```

The Agent has only the internal `agent-internal` network. The Gateway is the only dual-network service and publishes no host port.

## 4. Run with a real API credential file

The credential file must be mode `0600` and contain `MODEL_BASE_URL`, `MODEL_API_KEY`, and `MODEL_NAME`. The launcher sources it inside WSL, maps values only into the Gateway, mounts one exact per-run output directory, acquires the global evaluation lock, runs one batch, and always stops the Compose stack.

```bash
cd /home/taoxi/project/first
scripts/probe_model_env.sh \
  /home/taoxi/project/FinDver/FinDVer-SkillGraph/.env.agent models
sudo scripts/run_agent_with_env.sh \
  /home/taoxi/project/FinDver/FinDVer-SkillGraph/.env.agent \
  api tasks.jsonl real-agent-run
```

Gateway connections are direct by default. Set `GATEWAY_PROXY_URL` explicitly only when the container itself requires an HTTP proxy. Host `HTTP_PROXY` and `HTTPS_PROXY` values are intentionally not inherited.

The optional fifth and sixth arguments select `run|baseline` and a YAML filename under `configs/`. Examples:

```bash
sudo scripts/run_agent_with_env.sh ENV api tasks.jsonl b1 baseline baseline_cot_api.yaml
sudo scripts/run_agent_with_env.sh ENV api tasks.jsonl b2 baseline baseline_bm25_api.yaml
sudo scripts/run_agent_with_env.sh ENV api tasks.jsonl a0 run agent_no_calculator_api.yaml
sudo scripts/run_agent_with_env.sh ENV api tasks.jsonl a2 run agent_review_api.yaml
```

Use profile `local` and the corresponding `_local.yaml` files for a local OpenAI-compatible server. The fixed Gateway alias changes to `local-small-model`; the runtime contract stays identical.

## 5. Summarize, seal, and stop

```bash
cd /home/taoxi/project/first
.venv/bin/python scripts/summarize_run.py \
  --run-dir runs/real-agent-run \
  --output runs/real-agent-run/efficiency-summary.json
.venv/bin/python scripts/seal_submission.py \
  --run-dir runs/real-agent-run \
  --output runs/real-agent-run/submission.tar.gz
.venv/bin/python scripts/verify_submission.py \
  runs/real-agent-run/submission.tar.gz
sudo docker compose --project-name findver-agent \
  -f deploy/wsl/docker-compose.agent.yaml --profile api down --remove-orphans
```

The archive is deterministic, mode `0444`, and contains exactly `predictions.jsonl`, `manifest.json`, and `SHA256SUMS`. The efficiency summary is not placed in the submission.

## 6. Host-only one-way handoff

The target inbox must not already contain `submission.tar.gz`. The script acquires the same global evaluation lock, refuses handoff while either Compose project is running, validates the archive, copies it read-only, and verifies the copied hash. It never starts the scorer.

```bash
sudo /home/taoxi/project/first/scripts/handoff_submission.sh \
  /home/taoxi/project/first/runs/real-agent-run/submission.tar.gz \
  /home/taoxi/secure/FinDVer-Scorer-Private/inbox
```

## 7. Build and run the Private Scorer

Run these commands only after the Agent stack is stopped.

```bash
cd /home/taoxi/secure/FinDVer-Scorer-Private
/home/taoxi/project/first/.venv/bin/python -m pytest -q
sudo docker compose --project-name findver-scorer \
  -f deploy/wsl/docker-compose.scorer.yaml --profile score build private-scorer
sudo scripts/run_scorer.sh dev-detailed outputs/dev-run
sudo scripts/run_scorer.sh final-aggregate outputs/final-run
```

`dev-detailed` produces `summary.json` and private `feedback.jsonl`. `final-aggregate` produces only `summary.json`. Output directories must be new or empty and resolve below the scorer output root. The scorer has `network_mode: none`, no ports, and no Agent mounts.

The supplied `.env.scorer` is deliberately not injected: this scorer is deterministic and networkless, so an API key would be unused and would violate the data boundary.

## 8. Required isolation checks

Run inspection in a second terminal while the corresponding one-shot operation is active. Discover containers by Compose labels; do not rely on generated container names:

```bash
sudo docker ps --filter label=com.docker.compose.project=findver-agent
sudo docker inspect $(sudo docker ps -q \
  --filter label=com.docker.compose.project=findver-agent)

sudo docker ps -a --filter label=com.docker.compose.project=findver-scorer
sudo docker inspect $(sudo docker ps -aq \
  --filter label=com.docker.compose.project=findver-scorer)
```

Verify read-only roots, `CapDrop=[ALL]`, `no-new-privileges`, no published ports, no Docker socket, allowed mounts only, Agent internal network only, and Scorer `NetworkMode=none`. Never run Agent and Scorer containers simultaneously; the shared host lock also enforces this.
