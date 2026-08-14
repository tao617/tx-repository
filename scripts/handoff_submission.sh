#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_arg="${1:-}"
inbox_arg="${2:-/home/taoxi/secure/FinDVer-Scorer-Private/inbox}"
python_bin="${FINDVER_PYTHON:-$repo_root/.venv/bin/python}"

if [[ -z "$source_arg" ]]; then
  echo "usage: $0 SEALED_ARCHIVE [PRIVATE_SCORER_INBOX]" >&2
  exit 2
fi
exec 9>/run/lock/findver-evaluation.lock
if ! flock -n 9; then
  echo "another FinDVer Agent, handoff, or Scorer operation holds the evaluation lock" >&2
  exit 2
fi
if docker ps -q --filter label=com.docker.compose.project=findver-agent | grep -q .; then
  echo "refusing handoff while the Agent/Gateway project is running" >&2
  exit 2
fi
if docker ps -q --filter label=com.docker.compose.project=findver-scorer | grep -q .; then
  echo "refusing handoff while the Private Scorer project is running" >&2
  exit 2
fi

source_path="$(realpath "$source_arg")"
inbox_path="$(realpath -m "$inbox_arg")"
case "$source_path" in
  "$repo_root"/runs/*) ;;
  *) echo "sealed archive must be below $repo_root/runs" >&2; exit 2 ;;
esac
case "$inbox_path" in
  "$repo_root"|"$repo_root"/*) echo "private inbox cannot be inside the Agent repository" >&2; exit 2 ;;
esac
if [[ "$(stat -c %a "$source_path")" != "444" ]]; then
  echo "sealed archive must be immutable mode 0444" >&2
  exit 2
fi

"$python_bin" "$repo_root/scripts/verify_submission.py" "$source_path"
install -d -m 0700 "$inbox_path"
target="$inbox_path/submission.tar.gz"
if [[ -e "$target" ]]; then
  echo "refusing to overwrite existing scorer input: $target" >&2
  exit 2
fi
install -m 0444 "$source_path" "$target"
if [[ "$(sha256sum "$source_path" | cut -d' ' -f1)" != "$(sha256sum "$target" | cut -d' ' -f1)" ]]; then
  echo "handoff hash verification failed" >&2
  exit 2
fi
echo "handoff complete: $target"
