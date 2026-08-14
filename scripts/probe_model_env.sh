#!/usr/bin/env bash
set -euo pipefail

env_file="${1:-}"
mode="${2:-models}"
if [[ -z "$env_file" || ! -f "$env_file" ]]; then
  echo "usage: $0 PATH_TO_ENV_AGENT [models|chat]" >&2
  exit 2
fi
if [[ "$(stat -c %a "$env_file")" != "600" ]]; then
  echo "credential file must have mode 0600" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a
: "${MODEL_BASE_URL:?MODEL_BASE_URL is required}"
: "${MODEL_API_KEY:?MODEL_API_KEY is required}"
: "${MODEL_NAME:?MODEL_NAME is required}"

common=(
  --silent --show-error --output /dev/null --write-out '%{http_code}'
  --connect-timeout 10 --max-time 60
  --header "Authorization: Bearer $MODEL_API_KEY"
)
if [[ "$mode" == "models" ]]; then
  status="$(curl "${common[@]}" "${MODEL_BASE_URL%/}/models")"
elif [[ "$mode" == "chat" ]]; then
  payload="$(
    python3 -c 'import json, os; print(json.dumps({"model": os.environ["MODEL_NAME"], "messages": [{"role": "user", "content": "Reply with JSON."}], "temperature": 0, "max_tokens": 1}))'
  )"
  status="$(
    curl "${common[@]}" --header 'content-type: application/json' \
      --data "$payload" "${MODEL_BASE_URL%/}/chat/completions"
  )"
else
  echo "probe mode must be models or chat" >&2
  exit 2
fi
echo "model_${mode}_probe_http=$status"
[[ "$status" =~ ^2[0-9][0-9]$ ]]
