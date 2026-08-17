#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 local_api/familybot_api.py &
familybot_api_pid=$!

cleanup() {
  kill "$familybot_api_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

npm run dev:web
