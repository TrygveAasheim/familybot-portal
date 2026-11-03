#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

run_tool() {
  local package="$1"
  local command="$2"
  shift 2
  if command -v "$command" >/dev/null 2>&1; then
    "$command" "$@"
  elif command -v uv >/dev/null 2>&1; then
    uvx --from "$package" "$command" "$@"
  else
    echo "Missing $command. Install requirements-dev.txt or uv." >&2
    return 1
  fi
}

case "${1:-}" in
  lint)
    run_tool "ruff==0.17.3" ruff check local_api scripts local_service
    ;;
  security)
    run_tool "bandit==1.9.4" bandit -q -r local_api scripts local_service \
      -x '*/test_*.py' --severity-level medium --confidence-level medium
    run_tool "pip-audit==2.10.1" pip-audit -r requirements.txt --disable-pip
    ;;
  *)
    echo "Usage: $0 {lint|security}" >&2
    exit 2
    ;;
esac
