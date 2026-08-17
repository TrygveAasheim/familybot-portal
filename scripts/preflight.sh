#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE="${FAMILYBOT_WORKSPACE:-$HOME/.openclaw/workspace}"
PIN_FILE="$ROOT/runtime/parent-pin.txt"

if [[ -n "${FAMILYBOT_CONFIG_VALIDATOR:-}" ]]; then
  VALIDATOR="$FAMILYBOT_CONFIG_VALIDATOR"
elif [[ -f "$ROOT/../familybot-core/scripts/validate_config.py" ]]; then
  VALIDATOR="$ROOT/../familybot-core/scripts/validate_config.py"
elif [[ -f "$WORKSPACE/scripts/validate_config.py" ]]; then
  VALIDATOR="$WORKSPACE/scripts/validate_config.py"
else
  echo "Canonical validator not found. Clone familybot-core beside this repo or set FAMILYBOT_CONFIG_VALIDATOR." >&2
  exit 1
fi

python3 "$VALIDATOR"

if [[ ! -f "$PIN_FILE" ]]; then
  echo "Parent PIN file missing: $PIN_FILE" >&2
  exit 1
fi
if [[ "$(stat -f '%Lp' "$PIN_FILE")" != "600" ]]; then
  echo "Parent PIN must have mode 0600: $PIN_FILE" >&2
  exit 1
fi
PIN_LENGTH="$(tr -d '\r\n' < "$PIN_FILE" | wc -c | tr -d ' ')"
if (( PIN_LENGTH < 4 || PIN_LENGTH > 8 )); then
  echo "Parent PIN must contain 4-8 digits." >&2
  exit 1
fi
if ! LC_ALL=C tr -d '\r\n' < "$PIN_FILE" | grep -Eq '^[0-9]+$'; then
  echo "Parent PIN must contain digits only." >&2
  exit 1
fi

if [[ ! -f "$WORKSPACE/db/family.db" ]]; then
  echo "Family database missing: $WORKSPACE/db/family.db" >&2
  exit 1
fi
if [[ "$(sqlite3 "$WORKSPACE/db/family.db" 'PRAGMA integrity_check;')" != "ok" ]]; then
  echo "SQLite integrity check failed." >&2
  exit 1
fi

echo "Portal preflight OK."
