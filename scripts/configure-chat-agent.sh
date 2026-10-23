#!/bin/bash
set -euo pipefail

AGENT_ID="familybot-chat"
AGENT_ROOT="$HOME/.openclaw/agents/$AGENT_ID"
AGENT_WORKSPACE="$AGENT_ROOT/workspace"
MODEL="${FAMILYBOT_CHAT_MODEL:-openai/gpt-5.6-sol}"

install -d -m 700 "$AGENT_ROOT" "$AGENT_WORKSPACE"
if ! openclaw agents list --json | /usr/bin/python3 -c 'import json,sys; target=sys.argv[1]; raise SystemExit(0 if any(item.get("id")==target for item in json.load(sys.stdin)) else 1)' "$AGENT_ID"; then
  openclaw agents add "$AGENT_ID" --workspace "$AGENT_WORKSPACE" --agent-dir "$AGENT_ROOT/agent" --model "$MODEL" --non-interactive --json >/dev/null
fi

AGENT_INDEX="$(openclaw config get agents.list --json | /usr/bin/python3 -c 'import json,sys; target=sys.argv[1]; items=json.load(sys.stdin); print(next(index for index,item in enumerate(items) if item.get("id")==target))' "$AGENT_ID")"
openclaw config set "agents.list[$AGENT_INDEX].model" "\"$MODEL\"" --strict-json >/dev/null
openclaw config set "agents.list[$AGENT_INDEX].tools.profile" '"minimal"' --strict-json >/dev/null
openclaw config set "agents.list[$AGENT_INDEX].tools.elevated.enabled" 'false' --strict-json >/dev/null
openclaw config set "agents.list[$AGENT_INDEX].tools.deny" '["group:runtime","group:fs","group:web","group:memory","group:ui","group:automation","group:messaging","group:nodes","group:agents","group:media","group:plugins","cron","gateway"]' --strict-json >/dev/null
openclaw config set "agents.list[$AGENT_INDEX].skills" '[]' --strict-json >/dev/null

echo "FamilyBot chat agent configured with minimal read-only tool policy."
