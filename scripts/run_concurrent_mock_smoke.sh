#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
run_name="${1:-bclass-concurrent-mock}"
port="${2:-18081}"
task_name="concurrent-smoke-tasks.jsonl"
task_path="$repo_root/runtime_data/public/$task_name"
submission="$repo_root/submissions/$run_name.tar.gz"
temporary_env="$(mktemp /tmp/findver-concurrent-mock.XXXXXX.env)"
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
  if [[ "$temporary_env" == /tmp/findver-concurrent-mock.*.env ]]; then
    rm -f -- "$temporary_env"
  fi
}
trap cleanup EXIT

if [[ ! -f "$task_path" ]]; then
  echo "stage tests/fixtures/concurrent_smoke_tasks.jsonl as $task_path" >&2
  exit 2
fi
if [[ -e "$submission" ]]; then
  echo "concurrent smoke submission already exists: $submission" >&2
  exit 2
fi

python3 "$repo_root/tests/fixtures/mock_openai_server.py" \
  --host 0.0.0.0 \
  --port "$port" \
  --scenario immediate-submit &
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
  echo "concurrent mock server did not become ready" >&2
  exit 1
fi

printf '%s\n' \
  "MODEL_BASE_URL=http://host.docker.internal:${port}/v1" \
  'MODEL_API_KEY=builder-concurrent-mock-key' \
  'MODEL_NAME=builder-mock-upstream' \
  > "$temporary_env"
chmod 0600 "$temporary_env"

export FINDVER_UID="${FINDVER_UID:-$(id -u)}"
export FINDVER_GID="${FINDVER_GID:-$(id -g)}"
"$repo_root/scripts/run_agent_with_env.sh" \
  "$temporary_env" api "$task_name" "$run_name" run \
  bclass/api/A_SCRATCH.yaml

env \
  GIT_CONFIG_COUNT=1 \
  GIT_CONFIG_KEY_0=safe.directory \
  GIT_CONFIG_VALUE_0="$repo_root" \
  "$host_python" "$repo_root/scripts/seal_submission.py" \
  --run-dir "$repo_root/runs/$run_name" \
  --output "$submission"
env \
  GIT_CONFIG_COUNT=1 \
  GIT_CONFIG_KEY_0=safe.directory \
  GIT_CONFIG_VALUE_0="$repo_root" \
  "$host_python" "$repo_root/scripts/verify_concurrent_mock_smoke.py" \
  --run-dir "$repo_root/runs/$run_name" \
  --tasks "$task_path" \
  --submission "$submission"
