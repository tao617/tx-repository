# FinOASIS Experimental Runbook

## Authorization boundary

This runbook verifies protocol v3 only with tracked synthetic tasks, tracked synthetic
reports, the frozen synthetic rule corpus and the deterministic local mock server. The
four M3 configs declare `backend_kind: mock` and fix these fields:

```yaml
experimental: true
official_test_authorized: false
real_model_execution_authorized: false
scorer_handoff_authorized: false
```

Do not replace the mock upstream with a real model, use a paid credential, access the
1,700 official examples, prepare official artifacts, run the Private Scorer, or hand off
a v3 submission. Those operations require separate explicit authorization and, for
production rules or scorer certificates, a contract change.

## Recover the branch

```bash
cd /home/asus/2/tx-repository
git status --short
git branch --show-current
git log --oneline -10
cat AGENTS.md docs/PROJECT_CONTRACT.md
cat docs/FINOASIS_PROGRESS.md docs/STATE.yaml docs/SESSION_HANDOFF.md
```

The implementation branch is `feat/findoasis-obligation-skills`. The exact current
checkpoint and next action are recorded in the three recovery documents above.

## Python verification

Use Python 3.12 locally and retain Python 3.11 compatibility through public CI:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev,gateway]'
.venv/bin/python -m compileall -q src scripts tests
.venv/bin/pytest -q
git diff --check
```

In the recorded WSL/Codex environment, sandboxed Starlette `TestClient` threads hang;
the full suite is therefore run outside that sandbox with a repository-scoped
`--basetemp`. This is an environment constraint, not a product test failure.

Focused v3 verification:

```bash
.venv/bin/pytest -q \
  tests/unit/test_obligations_v3.py \
  tests/unit/test_actions_v3.py \
  tests/unit/test_state_v3.py \
  tests/unit/test_skill_router_v3.py \
  tests/unit/test_financial_dsl_v3.py \
  tests/unit/test_rule_corpus_v3.py \
  tests/unit/test_claim_verifier_v3.py \
  tests/integration/test_finoasis_e2e.py \
  tests/security
```

## Inspect the configurations

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from findver_agent.config import load_config

root = Path("configs/experimental/findoasis")
for path in sorted(root.glob("M3_*.yaml")):
    config = load_config(path)
    method = config.agent.findoasis
    print(path.name, method.obligation_policy.skill_exposure, method.enabled_skills)
PY

sha256sum \
  configs/experimental/findoasis/synthetic_rule_corpus/manifest.json \
  configs/experimental/findoasis/synthetic_rule_corpus/records.json
```

Expected corpus hashes:

- manifest: `549461e4b4a2fb1b8357b30f03589f62562db7a4b26ac8d38074b34080a4dc33`
- records: `4a3085d2b0d32a320fbc8e5b99527221e1abd161a3a277239732804873fe3436`

`M3_ALL_SKILLS_ALWAYS_EXPOSED.yaml` is an ablation and must not become the default.

## Credential-free in-process smoke

The integration test runs IE-only, Numeric, Knowledge and Mixed questions through the
real v3 orchestrator, Runner, state store, traces, certificate verifier and summary:

```bash
.venv/bin/pytest -q tests/integration/test_finoasis_e2e.py
```

It uses no socket or API credential. The scripted backend returns the same 26 strict v3
actions used by the container mock.

## Root-controlled Docker smoke

Do not add the interactive user to the `docker` group and do not change
`/var/run/docker.sock` permissions. Docker must remain root-controlled.

Stage only the tracked public fixtures:

```bash
install -m 0644 tests/fixtures/stateful_smoke_tasks.jsonl \
  runtime_data/public/smoke-tasks.jsonl
install -m 0644 tests/fixtures/concurrent_smoke_tasks.jsonl \
  runtime_data/public/concurrent-smoke-tasks.jsonl
install -m 0644 tests/fixtures/finoasis_smoke_tasks.jsonl \
  runtime_data/public/finoasis-smoke-tasks.jsonl
```

Run all three gates with unique run names and ports:

```bash
sudo env FINDVER_UID="$(id -u)" FINDVER_GID="$(id -g)" \
  scripts/run_stateful_mock_smoke.sh phase8-stateful 18080
sudo env FINDVER_UID="$(id -u)" FINDVER_GID="$(id -g)" \
  scripts/run_concurrent_mock_smoke.sh phase8-concurrent 18081
sudo env FINDVER_UID="$(id -u)" FINDVER_GID="$(id -g)" \
  scripts/run_finoasis_mock_smoke.sh phase8-finoasis 18082
```

The scripts create an ephemeral mode-0600 environment file containing only a dummy
local mock token, start a deterministic host server, rebuild Agent and Gateway images,
run the CLI in the read-only Runtime, verify outputs and tear the Compose project down.
No real provider is contacted. The v3 script mounts only the tracked synthetic report
directory at the existing read-only `/reports` target.

If a no-new-privileges automation shell cannot perform interactive sudo, use the WSL
host's approved root execution mechanism; do not work around it by granting Docker group
membership or broadening the socket.

## Verify v3 output and summary

```bash
.venv/bin/python scripts/verify_finoasis_mock_smoke.py \
  --run-dir runs/phase8-finoasis \
  --tasks runtime_data/public/finoasis-smoke-tasks.jsonl
.venv/bin/python scripts/summarize_run.py \
  --run-dir runs/phase8-finoasis \
  --output runs/phase8-finoasis/efficiency-summary.json
```

The verifier requires four completed predictions, dynamic IE masking, Numeric-only and
Knowledge-only specialist paths, a Mixed final certificate containing both specialist
proof families, and aggregate output free of task/evidence text.

The summary is not a scorer artifact. It contains aggregate obligation, routing,
numeric, rule and Runtime-cost counters. Final certificates remain in per-question
state and trace; no new sidecar is created.

## Fail-closed recovery

- Resume only with the identical task, report, config, Registry, policy and corpus
  hashes. Drift is an error; do not delete state to conceal it.
- A hidden or wrong-target Skill action consumes its model attempt and mutates no proof
  ledger.
- A corpus hash/path failure blocks Knowledge Skills. Do not enable network fallback.
- An invalid/tampered certificate cannot become a low-confidence fallback.
- Do not seal or hand off a v3 run to the Private Scorer while
  `scorer_handoff_authorized` is false.
- Keep `docs/PROJECT_CONTRACT.md`, `docs/OFFICIAL_TEST_V2_FREEZE_PLAN.md` and
  `experiments/official_test_v2_freeze.yaml` unchanged.
