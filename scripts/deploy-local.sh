#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${FAMILYBOT_PORTAL_RUNTIME:-$HOME/.openclaw/runtime/familybot-portal}"
PLIST="$HOME/Library/LaunchAgents/ai.familybot.portal.plist"
IMAGE_PLIST="$HOME/Library/LaunchAgents/ai.familybot.portal-images.plist"
UID_VALUE="$(id -u)"
PLIST_TEMP="$(mktemp -t familybot-portal-plist)"
IMAGE_PLIST_TEMP="$(mktemp -t familybot-portal-images-plist)"
UV_BIN="${FAMILYBOT_UV:-$(command -v uv || true)}"
trap 'rm -f "$PLIST_TEMP" "$IMAGE_PLIST_TEMP"' EXIT

cd "$ROOT"
CURRENT_BRANCH="$(git branch --show-current)"
if [[ "$CURRENT_BRANCH" != "dev" ]]; then
  echo "Refusing deployment from '$CURRENT_BRANCH'. Deploy only from dev." >&2
  exit 1
fi
npm run preflight
npm run lint
npm test
./scripts/configure-oda-dinner-agent.sh
python3 local_api/dashboard_migration.py --repair-default-rewards
if [[ -z "$UV_BIN" ]]; then
  echo "uv is required to build the isolated Portal Python runtime (brew install uv)." >&2
  exit 1
fi
mkdir -p "$TARGET/local_api" "$TARGET/local_service" "$TARGET/scripts" "$TARGET/runtime"
if [[ ! -x "$TARGET/.venv/bin/python" ]]; then
  "$UV_BIN" venv --python 3.12 "$TARGET/.venv"
fi
"$UV_BIN" pip sync --python "$TARGET/.venv/bin/python" "$ROOT/requirements.txt"
"$UV_BIN" pip check --python "$TARGET/.venv/bin/python"
"$TARGET/.venv/bin/python" -c "import curl_cffi"

# Stop the managed service before replacing its runtime tree. Updating files
# underneath a running Node process can otherwise trigger a restart against a
# half-copied node_modules directory.
launchctl bootout "gui/$UID_VALUE/ai.familybot.portal" 2>/dev/null || true
launchctl bootout "gui/$UID_VALUE/ai.familybot.portal-images" 2>/dev/null || true

rm -f "$TARGET/local_api/familybot_chat.py"
rsync -a --delete dist/standalone/ "$TARGET/dist/standalone/"
rsync -a node_modules/react node_modules/react-dom node_modules/scheduler "$TARGET/dist/standalone/node_modules/"
rsync -a local_api/familybot_api.py local_api/hellofresh_account.py local_api/hellofresh_images.py local_api/hellofresh_norway.py local_api/oda_mcp.py local_api/oda_dinner.py local_api/dashboard_migration.py local_api/family_config.py "$TARGET/local_api/"
rsync -a local_service/run_service.py "$TARGET/local_service/"
rsync -a scripts/child_chore.py scripts/prefetch_hellofresh_images.py "$TARGET/scripts/"
rsync -a requirements.txt "$TARGET/"
if [[ -f "$ROOT/runtime/parent-pin.txt" ]]; then
  rsync -a "$ROOT/runtime/parent-pin.txt" "$TARGET/runtime/"
fi
chmod 600 "$TARGET/runtime/parent-pin.txt"
sed "s|/Users/YOUR_ACCOUNT|$HOME|g" launchd/ai.familybot.portal.plist > "$PLIST_TEMP"
sed "s|/Users/YOUR_ACCOUNT|$HOME|g" launchd/ai.familybot.portal-images.plist > "$IMAGE_PLIST_TEMP"
install -m 600 "$PLIST_TEMP" "$PLIST"
install -m 600 "$IMAGE_PLIST_TEMP" "$IMAGE_PLIST"
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
launchctl kickstart -k "gui/$UID_VALUE/ai.familybot.portal"
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
echo "Familieportalen deployed: http://familie.local:3000/"
