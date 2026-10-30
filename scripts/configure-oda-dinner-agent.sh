#!/bin/bash
set -euo pipefail

AGENT_ID="${FAMILYBOT_ODA_DINNER_AGENT:-familybot-oda-dinner}"
AGENT_ROOT="$HOME/.openclaw/agents/$AGENT_ID"
AGENT_WORKSPACE="$AGENT_ROOT/workspace"
MODEL="${FAMILYBOT_ODA_DINNER_MODEL:-openai/gpt-5.6-sol}"
OPENCLAW_BIN="${FAMILYBOT_OPENCLAW:-/opt/homebrew/bin/openclaw}"

if [[ ! -x "$OPENCLAW_BIN" ]]; then
  echo "OpenClaw is unavailable; Oda dinner search will use its deterministic fallback." >&2
  exit 0
fi

install -d -m 700 "$AGENT_ROOT" "$AGENT_WORKSPACE"
if ! "$OPENCLAW_BIN" agents list --json | /usr/bin/python3 -c 'import json,sys; target=sys.argv[1]; raise SystemExit(0 if any(item.get("id")==target for item in json.load(sys.stdin)) else 1)' "$AGENT_ID"; then
  "$OPENCLAW_BIN" agents add "$AGENT_ID" --workspace "$AGENT_WORKSPACE" --agent-dir "$AGENT_ROOT/agent" --model "$MODEL" --non-interactive --json >/dev/null
fi

AGENT_INDEX="$("$OPENCLAW_BIN" config get agents.list --json | /usr/bin/python3 -c 'import json,sys; target=sys.argv[1]; items=json.load(sys.stdin); print(next(index for index,item in enumerate(items) if item.get("id")==target))' "$AGENT_ID")"
"$OPENCLAW_BIN" config set "agents.list[$AGENT_INDEX].model" "\"$MODEL\"" --strict-json >/dev/null
"$OPENCLAW_BIN" config set "agents.list[$AGENT_INDEX].tools.profile" '"minimal"' --strict-json >/dev/null
"$OPENCLAW_BIN" config set "agents.list[$AGENT_INDEX].tools.allow" '[]' --strict-json >/dev/null
"$OPENCLAW_BIN" config set "agents.list[$AGENT_INDEX].tools.alsoAllow" '[]' --strict-json >/dev/null
"$OPENCLAW_BIN" config set "agents.list[$AGENT_INDEX].tools.elevated.enabled" 'false' --strict-json >/dev/null
"$OPENCLAW_BIN" config set "agents.list[$AGENT_INDEX].tools.deny" '["group:runtime","group:fs","group:web","group:memory","group:ui","group:automation","group:messaging","group:nodes","group:agents","group:media","group:plugins","cron","gateway"]' --strict-json >/dev/null
"$OPENCLAW_BIN" config set "agents.list[$AGENT_INDEX].skills" '[]' --strict-json >/dev/null
"$OPENCLAW_BIN" config validate >/dev/null

echo "Oda dinner planner configured as an isolated, tool-free OpenAI agent."
