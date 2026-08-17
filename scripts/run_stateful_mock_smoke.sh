#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
run_name="${1:-bclass-stateful-mock-m2}"
port="${2:-18080}"
config_name="${3:-bclass/api/M2_SELECTIVE_REVIEW.yaml}"
temporary_env="$(mktemp /tmp/findver-stateful-mock.XXXXXX.env)"
mock_pid=""

cleanup() {
  if [[ -n "$mock_pid" ]]; then
    kill "$mock_pid" >/dev/null 2>&1 || true
    wait "$mock_pid" >/dev/null 2>&1 || true
  fi
  if [[ "$temporary_env" == /tmp/findver-stateful-mock.*.env ]]; then
    rm -f -- "$temporary_env"
  fi
}
trap cleanup EXIT

python3 "$repo_root/tests/fixtures/mock_openai_server.py" \
  --host 0.0.0.0 \
  --port "$port" \
  --scenario m2-review-fallback &
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
  echo "stateful mock server did not become ready" >&2
  exit 1
fi

printf '%s\n' \
  "MODEL_BASE_URL=http://host.docker.internal:${port}/v1" \
  'MODEL_API_KEY=builder-stateful-mock-key' \
  'MODEL_NAME=builder-mock-upstream' \
  > "$temporary_env"
chmod 0600 "$temporary_env"

export FINDVER_UID="${FINDVER_UID:-$(id -u)}"
export FINDVER_GID="${FINDVER_GID:-$(id -g)}"
"$repo_root/scripts/run_agent_with_env.sh" \
  "$temporary_env" api smoke-tasks.jsonl "$run_name" run \
  "$config_name"

verification=(
  python3 "$repo_root/scripts/verify_stateful_mock_smoke.py"
  --run-dir "$repo_root/runs/$run_name"
)
if [[ "$config_name" == "bclass/ablations/LC_AGENT_FIRSTPASS.yaml" ]]; then
  verification+=(--expect-long-context)
fi
"${verification[@]}"
