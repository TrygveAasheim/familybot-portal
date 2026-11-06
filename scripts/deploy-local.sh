#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  export PATH="$ROOT/.venv/bin:$PATH"
fi
WORKSPACE="${FAMILYBOT_WORKSPACE:-${OPENCLAW_WORKSPACE:-$HOME/.familybot}}"
TARGET="${FAMILYBOT_PORTAL_RUNTIME:-$WORKSPACE/runtime/familybot-portal}"
FAMILY_CONFIG="${FAMILYBOT_FAMILY_CONFIG:-$WORKSPACE/config/family.local.json}"
PIN_FILE="${FAMILYBOT_PARENT_PIN_FILE:-$WORKSPACE/config/parent-pin.txt}"
if [[ ! -f "$PIN_FILE" && -f "$ROOT/runtime/parent-pin.txt" ]]; then
  PIN_FILE="$ROOT/runtime/parent-pin.txt"
fi
LAUNCH_DIR="${FAMILYBOT_LAUNCHAGENT_DIR:-$HOME/Library/LaunchAgents}"
SERVICE_LABEL="${FAMILYBOT_PORTAL_LABEL:-ai.familybot.portal}"
if [[ ! "$SERVICE_LABEL" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]+$ ]]; then
  echo "Invalid Portal LaunchAgent label." >&2
  exit 1
fi
PLIST="$LAUNCH_DIR/$SERVICE_LABEL.plist"
IMAGE_PLIST="$LAUNCH_DIR/$SERVICE_LABEL-images.plist"
export FAMILYBOT_PORTAL_LABEL="$SERVICE_LABEL"
UID_VALUE="$(id -u)"
PLIST_TEMP="$(mktemp -t familybot-portal-plist)"
IMAGE_PLIST_TEMP="$(mktemp -t familybot-portal-images-plist)"
UV_BIN="${FAMILYBOT_UV:-$(command -v uv || true)}"
NODE_BIN="${FAMILYBOT_NODE:-$(command -v node || true)}"
PYTHON_BIN="${FAMILYBOT_PYTHON:-$(command -v python3 || true)}"
trap 'rm -f "$PLIST_TEMP" "$IMAGE_PLIST_TEMP"' EXIT

render_plist() {
  local template_path="$1"
  local target_path="$2"
  FAMILYBOT_PLIST_TEMPLATE="$template_path" \
  FAMILYBOT_PLIST_TARGET="$target_path" \
  FAMILYBOT_PLIST_HOME="$HOME" \
  FAMILYBOT_PLIST_NODE="$NODE_BIN" \
  FAMILYBOT_PLIST_RUNTIME="$TARGET" \
  FAMILYBOT_PLIST_WORKSPACE="$WORKSPACE" \
  FAMILYBOT_PLIST_CONFIG="$FAMILY_CONFIG" \
    "$PYTHON_BIN" - <<'PY'
import os
import plistlib
from pathlib import Path

source = Path(os.environ["FAMILYBOT_PLIST_TEMPLATE"])
target = Path(os.environ["FAMILYBOT_PLIST_TARGET"])
replacements = {
    "/Users/YOUR_ACCOUNT": os.environ["FAMILYBOT_PLIST_HOME"],
    "__FAMILYBOT_NODE__": os.environ["FAMILYBOT_PLIST_NODE"],
    "__FAMILYBOT_RUNTIME__": os.environ["FAMILYBOT_PLIST_RUNTIME"],
    "__FAMILYBOT_WORKSPACE__": os.environ["FAMILYBOT_PLIST_WORKSPACE"],
    "__FAMILYBOT_CONFIG__": os.environ["FAMILYBOT_PLIST_CONFIG"],
}


def substitute(value):
    if isinstance(value, str):
        for placeholder, replacement in replacements.items():
            value = value.replace(placeholder, replacement)
        return value
    if isinstance(value, list):
        return [substitute(item) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item) for key, item in value.items()}
    return value


with source.open("rb") as handle:
    document = plistlib.load(handle)
rendered = plistlib.dumps(substitute(document), fmt=plistlib.FMT_XML, sort_keys=False)
document = plistlib.loads(rendered)
document["Label"] = os.environ["FAMILYBOT_PORTAL_LABEL"] + ("-images" if "images" in source.name else "")
rendered = plistlib.dumps(document, fmt=plistlib.FMT_XML, sort_keys=False)
target.write_bytes(rendered)
PY
}

cd "$ROOT"
CURRENT_BRANCH="$(git branch --show-current)"
CURRENT_BRANCH="${CURRENT_BRANCH:-$(git rev-parse HEAD)}"
DEPLOY_BRANCH="${FAMILYBOT_DEPLOY_BRANCH:-dev}"
if [[ "$CURRENT_BRANCH" != "$DEPLOY_BRANCH" ]]; then
  echo "Refusing deployment from '$CURRENT_BRANCH'. Expected '$DEPLOY_BRANCH'." >&2
  echo "Fork maintainers may set FAMILYBOT_DEPLOY_BRANCH to their reviewed release branch." >&2
  exit 1
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Python 3.12 or newer is required to deploy the Portal." >&2
  exit 1
fi
if [[ -z "$UV_BIN" ]]; then
  echo "uv is required to build the isolated Portal Python runtime (brew install uv)." >&2
  exit 1
fi
if [[ -z "$NODE_BIN" ]]; then
  echo "Node.js is required to run the Portal service." >&2
  exit 1
fi
if ! launchctl print "gui/$UID_VALUE" >/dev/null 2>&1; then
  echo "No user GUI launchd domain. Log into the Mac desktop as this user before installation." >&2
  exit 1
fi
export VITE_FAMILYBOT_API_PORT
VITE_FAMILYBOT_API_PORT="$("$PYTHON_BIN" - "$FAMILY_CONFIG" <<'PY'
import json
import sys
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(int(config.get("portal", {}).get("api_port", 8788)))
PY
)"
FAMILYBOT_ALLOW_PENDING_PORTAL_SCHEMA=1 npm run preflight
npm run lint
npm test
FEATURES="$("$PYTHON_BIN" - "$FAMILY_CONFIG" <<'PY'
import json
import sys
from pathlib import Path
config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
features = config.get("portal", {}).get("features", {})
print("oda_ai" if features.get("oda") is True and features.get("oda_ai") is True else "")
print("hellofresh" if features.get("hellofresh") is True else "")
print("hellofresh_account" if features.get("hellofresh") is True and features.get("hellofresh_account") is True else "")
PY
)"
if printf '%s\n' "$FEATURES" | grep -Fxq "oda_ai"; then
  ./scripts/configure-oda-dinner-agent.sh
fi
# Default rewards are first-install data, not an upgrade repair. An intentional
# parent deactivation must survive deployment; repair remains a separate CLI.
"$PYTHON_BIN" local_api/dashboard_migration.py
"$PYTHON_BIN" local_api/dashboard_migration.py --status >/dev/null
mkdir -p "$TARGET/local_api" "$TARGET/local_service" "$TARGET/scripts" "$TARGET/runtime"
mkdir -p "$LAUNCH_DIR" "$HOME/Library/Logs"
if [[ ! -x "$TARGET/.venv/bin/python" ]]; then
  "$UV_BIN" venv --python 3.12 "$TARGET/.venv"
fi
RUNTIME_REQUIREMENTS="$ROOT/requirements-base.txt"
if printf '%s\n' "$FEATURES" | grep -Fxq "hellofresh"; then
  RUNTIME_REQUIREMENTS="$ROOT/requirements.txt"
fi
"$UV_BIN" pip sync --allow-empty-requirements \
  --python "$TARGET/.venv/bin/python" "$RUNTIME_REQUIREMENTS"
"$UV_BIN" pip check --python "$TARGET/.venv/bin/python"
if printf '%s\n' "$FEATURES" | grep -Fxq "hellofresh"; then
  "$TARGET/.venv/bin/python" -c "import curl_cffi"
fi

# Stop the managed service before replacing its runtime tree. Updating files
# underneath a running Node process can otherwise trigger a restart against a
# half-copied node_modules directory.
launchctl bootout "gui/$UID_VALUE/$SERVICE_LABEL" 2>/dev/null || true
launchctl bootout "gui/$UID_VALUE/$SERVICE_LABEL-images" 2>/dev/null || true

rm -f "$TARGET/local_api/familybot_chat.py"
rsync -a --delete dist/standalone/ "$TARGET/dist/standalone/"
rsync -a node_modules/react node_modules/react-dom node_modules/scheduler "$TARGET/dist/standalone/node_modules/"
rsync -a local_api/familybot_api.py local_api/hellofresh_account.py local_api/hellofresh_account_contract.py local_api/hellofresh_account_mutations.py local_api/hellofresh_account_recipe.py local_api/hellofresh_account_transport.py local_api/hellofresh_images.py local_api/hellofresh_norway.py local_api/oda_mcp.py local_api/oda_dinner.py local_api/dashboard_migration.py local_api/family_config.py "$TARGET/local_api/"
rsync -a local_service/run_service.py "$TARGET/local_service/"
rsync -a scripts/check_hellofresh_contract.py scripts/child_chore.py scripts/prefetch_hellofresh_images.py "$TARGET/scripts/"
rsync -a requirements.txt requirements-base.txt "$TARGET/"
install -m 600 "$PIN_FILE" "$TARGET/runtime/parent-pin.txt"
chmod 600 "$TARGET/runtime/parent-pin.txt"
render_plist launchd/ai.familybot.portal.plist "$PLIST_TEMP"
render_plist launchd/ai.familybot.portal-images.plist "$IMAGE_PLIST_TEMP"
install -m 600 "$PLIST_TEMP" "$PLIST"
if printf '%s\n' "$FEATURES" | grep -Fxq "hellofresh_account"; then
  install -m 600 "$IMAGE_PLIST_TEMP" "$IMAGE_PLIST"
elif [[ -f "$IMAGE_PLIST" ]]; then
  rm "$IMAGE_PLIST"
  echo "Removed disabled generated HelloFresh image job."
fi
for attempt in 1 2 3; do
  if launchctl bootstrap "gui/$UID_VALUE" "$PLIST"; then
    break
  fi
  if [[ "$attempt" -eq 3 ]]; then
    echo "Could not register Familieportalen after 3 attempts." >&2
    exit 1
  fi
  sleep 2
done
launchctl kickstart -k "gui/$UID_VALUE/$SERVICE_LABEL"
if printf '%s\n' "$FEATURES" | grep -Fxq "hellofresh_account"; then
  for attempt in 1 2 3; do
    if launchctl bootstrap "gui/$UID_VALUE" "$IMAGE_PLIST"; then
      break
    fi
    if [[ "$attempt" -eq 3 ]]; then
      echo "Could not register HelloFresh image prefetch after 3 attempts." >&2
      exit 1
    fi
    sleep 2
  done
fi
echo "Familieportalen deployed using the hostname and ports in the selected family configuration."
