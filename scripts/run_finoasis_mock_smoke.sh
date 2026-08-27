#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
run_name="${1:-finoasis-v3-mock}"
port="${2:-18082}"
task_name="finoasis-smoke-tasks.jsonl"
task_path="$repo_root/runtime_data/public/$task_name"
temporary_env="$(mktemp /tmp/findver-finoasis-mock.XXXXXX.env)"
mock_pid=""
host_python="${FINDVER_HOST_PYTHON:-python3}"
if [[ -x "$repo_root/.venv/bin/python" ]]; then
  host_python="$repo_root/.venv/bin/python"
fi

cleanup() {
  if [[ -n "$mock_pid" ]]; then
    kill "$mock_pid" >/dev/null 2>&1 || true
    wait "$mock_pid" >/dev/null 2>&1 || true
  fi
  if [[ "$temporary_env" == /tmp/findver-finoasis-mock.*.env ]]; then
    rm -f -- "$temporary_env"
  fi
}
trap cleanup EXIT

if [[ ! -f "$task_path" ]]; then
  echo "stage tests/fixtures/finoasis_smoke_tasks.jsonl as $task_path" >&2
  exit 2
fi
if [[ -e "$repo_root/runs/$run_name" ]]; then
  echo "FinOASIS smoke run already exists: $repo_root/runs/$run_name" >&2
  exit 2
fi

python3 "$repo_root/tests/fixtures/mock_openai_server.py" \
  --host 0.0.0.0 \
  --port "$port" \
  --scenario finoasis-v3 &
mock_pid="$!"

ready=0
for _ in $(seq 1 30); do
  if python3 -c \
    'import socket, sys; socket.create_connection(("127.0.0.1", int(sys.argv[1])), 1).close()' \
    "$port" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.2
done
if [[ "$ready" != "1" ]]; then
  echo "FinOASIS mock server did not become ready" >&2
  exit 1
fi

printf '%s\n' \
  "MODEL_BASE_URL=http://host.docker.internal:${port}/v1" \
  'MODEL_API_KEY=builder-finoasis-local-mock-only' \
  'MODEL_NAME=builder-mock-upstream' \
  > "$temporary_env"
chmod 0600 "$temporary_env"

export FINDVER_UID="${FINDVER_UID:-$(id -u)}"
export FINDVER_GID="${FINDVER_GID:-$(id -g)}"
export FINDVER_REPORTS_SOURCE="$repo_root/tests/fixtures/finoasis_smoke_reports"
"$repo_root/scripts/run_agent_with_env.sh" \
  "$temporary_env" api "$task_name" "$run_name" run \
  experimental/findoasis/M3_ALL_SKILLS_SYNTHETIC.yaml

"$host_python" "$repo_root/scripts/summarize_run.py" \
  --run-dir "$repo_root/runs/$run_name" \
  --output "$repo_root/runs/$run_name/efficiency-summary.json"
"$host_python" "$repo_root/scripts/verify_finoasis_mock_smoke.py" \
  --run-dir "$repo_root/runs/$run_name" \
  --tasks "$task_path"
