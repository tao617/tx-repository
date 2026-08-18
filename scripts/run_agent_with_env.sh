#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${1:-}"
profile="${2:-}"
task_name="${3:-}"
run_name="${4:-}"
command_name="${5:-run}"
config_name="${6:-}"
resume_flag="${7:-}"

if [[ -z "$env_file" || -z "$task_name" || -z "$run_name" ]]; then
  echo "usage: $0 PATH_TO_ENV_AGENT {api|local} PUBLIC_TASK_FILENAME RUN_NAME [run|baseline|iterative-rag] [CONFIG_PATH_UNDER_CONFIGS] [--resume]" >&2
  exit 2
fi
if [[ "$profile" != "api" && "$profile" != "local" ]]; then
  echo "profile must be api or local" >&2
  exit 2
fi
if [[ "$command_name" != "run" && "$command_name" != "baseline" && "$command_name" != "iterative-rag" ]]; then
  echo "command must be run, baseline, or iterative-rag" >&2
  exit 2
fi
if [[ -n "$resume_flag" && "$resume_flag" != "--resume" ]]; then
  echo "seventh argument must be --resume when provided" >&2
  exit 2
fi
if [[ -z "$config_name" ]]; then
  if [[ "$command_name" == "run" ]]; then
    config_name="agent_${profile}.yaml"
  elif [[ "$command_name" == "baseline" ]]; then
    config_name="baseline_${profile}.yaml"
  else
    echo "iterative-rag requires an explicit config path" >&2
    exit 2
  fi
fi
if [[ ! "$task_name" =~ ^[A-Za-z0-9._-]+$ || ! "$run_name" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "task and run names must be plain filenames" >&2
  exit 2
fi
if [[ ! -f "$env_file" || "$(stat -c %a "$env_file")" != "600" ]]; then
  echo "credential file must exist with mode 0600" >&2
  exit 2
fi
config_mount=()
if [[ "$config_name" =~ ^@effective/([a-f0-9]{64}\.json)$ ]]; then
  effective_name="${BASH_REMATCH[1]}"
  config_path="$(realpath -e -- "$repo_root/runtime_data/effective_configs/$effective_name")"
  if [[ "$config_path" != "$repo_root/runtime_data/effective_configs/$effective_name" ]]; then
    echo "effective configuration must resolve beneath runtime_data/effective_configs" >&2
    exit 2
  fi
  runtime_config_path="/effective-config/config.json"
  config_mount=(--volume "$config_path:$runtime_config_path:ro")
else
  if [[ ! "$config_name" =~ ^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*\.yaml$ ]]; then
    echo "configuration must be a safe path under configs or a bound effective config" >&2
    exit 2
  fi
  IFS='/' read -r -a config_segments <<< "$config_name"
  for segment in "${config_segments[@]}"; do
    if [[ "$segment" == "." || "$segment" == ".." ]]; then
      echo "configuration path cannot contain dot segments" >&2
      exit 2
    fi
  done
  config_path="$(realpath -e -- "$repo_root/configs/$config_name")"
  case "$config_path" in
    "$repo_root/configs/"*) ;;
    *)
      echo "configuration must resolve beneath configs" >&2
      exit 2
      ;;
  esac
  runtime_config_path="/app/configs/$config_name"
fi
lock_path=/run/lock/findver-evaluation.lock
if [[ ! -e "$lock_path" ]]; then
  (umask 022; set -o noclobber; : > "$lock_path") 2>/dev/null || true
fi
exec 9<"$lock_path"
if ! flock -n 9; then
  echo "another FinDVer Agent, handoff, or Scorer operation holds the evaluation lock" >&2
  exit 2
fi
if [[ ! -f "$repo_root/runtime_data/public/$task_name" ]]; then
  echo "public task file does not exist" >&2
  exit 2
fi
if [[ "$resume_flag" == "--resume" ]]; then
  if [[ ! -d "$repo_root/runs/$run_name" || ! -f "$repo_root/runs/$run_name/run_metadata.json" ]]; then
    echo "resume requires an existing run directory with metadata" >&2
    exit 2
  fi
else
  if [[ -e "$repo_root/runs/$run_name" ]]; then
    echo "run directory already exists; pass --resume to continue it" >&2
    exit 2
  fi
fi

planned_run_identity_json="${FINDVER_RUN_IDENTITY_JSON:-}"
planned_expected_model_id="${FINDVER_EXPECTED_MODEL_ID:-}"
set -a
# shellcheck disable=SC1090
source "$env_file"
set +a
unset COMPOSE_FILE COMPOSE_PROFILES COMPOSE_PROJECT_NAME
: "${MODEL_BASE_URL:?MODEL_BASE_URL is required}"
: "${MODEL_API_KEY:?MODEL_API_KEY is required}"
: "${MODEL_NAME:?MODEL_NAME is required}"

run_identity_json="$planned_run_identity_json"
expected_model_id="$planned_expected_model_id"
if [[ -n "$expected_model_id" ]]; then
  if [[ -z "$run_identity_json" ]]; then
    echo "planned run requires FINDVER_RUN_IDENTITY_JSON" >&2
    exit 2
  fi
  identity_model_id="$(
    python3 -c \
      'import json, os; print(json.loads(os.environ["FINDVER_RUN_IDENTITY_JSON"])["effective_model_id"])'
  )"
  if [[ "$MODEL_NAME" != "$expected_model_id" || "$identity_model_id" != "$MODEL_NAME" ]]; then
    echo "MODEL_NAME does not match the planned effective model ID" >&2
    exit 2
  fi
fi

export MODEL_UPSTREAM_BASE_URL="$MODEL_BASE_URL"
export MODEL_UPSTREAM_MODEL="$MODEL_NAME"
if [[ "$profile" == "api" ]]; then
  export MODEL_ALIASES="external-model-name"
else
  export MODEL_ALIASES="local-small-model"
fi

proxy_url="${GATEWAY_PROXY_URL:-}"
export GATEWAY_HTTP_PROXY="$proxy_url"
export GATEWAY_HTTPS_PROXY="$proxy_url"
export GATEWAY_NO_PROXY="127.0.0.1,localhost,model-gateway"

runtime_uid="${FINDVER_UID:-1000}"
runtime_gid="${FINDVER_GID:-1000}"
install -d -m 0700 -o "$runtime_uid" -g "$runtime_gid" "$repo_root/runs/$run_name"
export FINDVER_RUN_OUTPUT_DIR="$repo_root/runs/$run_name"
export FINDVER_RUN_NAME="$run_name"

compose=(
  docker compose --project-name findver-agent
  -f "$repo_root/deploy/wsl/docker-compose.agent.yaml" --profile "$profile"
)
cleanup() {
  "${compose[@]}" down --remove-orphans >/dev/null
}
trap cleanup EXIT

if docker ps -q --filter label=com.docker.compose.project=findver-scorer | grep -q .; then
  echo "refusing to run while the Private Scorer project is active" >&2
  exit 2
fi
"${compose[@]}" build model-gateway agent-runtime
"${compose[@]}" up -d model-gateway
runtime_command=(
  python -m findver_agent.cli "$command_name"
  --config "$runtime_config_path"
  --tasks "/public/$task_name"
  --reports /reports
  --run-dir "/output/$run_name"
)
if [[ -n "$run_identity_json" ]]; then
  runtime_command+=(--run-identity-json "$run_identity_json")
fi
"${compose[@]}" run --rm "${config_mount[@]}" agent-runtime "${runtime_command[@]}"
if [[ "${GATEWAY_DIAGNOSTICS:-0}" == "1" ]]; then
  "${compose[@]}" logs --no-color --tail 50 model-gateway >&2
fi
