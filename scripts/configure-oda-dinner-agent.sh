#!/bin/bash
set -euo pipefail

AGENT_ID="${FAMILYBOT_ODA_DINNER_AGENT:-familybot-oda-dinner}"
MODEL="${FAMILYBOT_ODA_DINNER_MODEL:-openai/gpt-5.6-sol}"
if [[ ! "$AGENT_ID" =~ ^[a-z0-9][a-z0-9-]{0,63}$ ]] ||
   [[ ! "$MODEL" =~ ^[a-z0-9][a-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "Invalid dinner agent or model id." >&2
  exit 64
fi
AGENT_ROOT="$HOME/.openclaw/agents/$AGENT_ID"
AGENT_WORKSPACE="$AGENT_ROOT/workspace"
OPENCLAW_BIN="${FAMILYBOT_OPENCLAW:-$(command -v openclaw || true)}"

if [[ -z "$OPENCLAW_BIN" || ! -x "$OPENCLAW_BIN" ]]; then
  echo "OpenClaw is unavailable; Oda dinner search will use its deterministic fallback." >&2
  exit 0
fi

install -d -m 700 "$AGENT_ROOT" "$AGENT_WORKSPACE"
EXISTING="$("$OPENCLAW_BIN" agents list --json | /usr/bin/python3 -c 'import json,sys; target=sys.argv[1]; items=json.load(sys.stdin)
if not isinstance(items,list) or not all(isinstance(item,dict) and isinstance(item.get("id"),str) for item in items):
    raise SystemExit("Invalid OpenClaw agent inventory.")
print("present" if any(item.get("id")==target for item in items) else "absent")' "$AGENT_ID")"
if [[ "$EXISTING" == "absent" ]]; then
  "$OPENCLAW_BIN" agents add "$AGENT_ID" --workspace "$AGENT_WORKSPACE" --agent-dir "$AGENT_ROOT/agent" --model "$MODEL" --non-interactive --json >/dev/null
fi

AGENT_PATH="$("$OPENCLAW_BIN" config get agents --json | /usr/bin/python3 -c '
import json,sys
target=sys.argv[1]
roster=json.load(sys.stdin)
def require(condition):
    if not condition:
        raise SystemExit("Invalid or ambiguous OpenClaw agent inventory.")
require(isinstance(roster,dict))
if "entries" in roster:
    entries=roster["entries"]
    require(isinstance(entries,dict) and isinstance(entries.get(target),dict))
    print("agents.entries."+target)
else:
    items=roster["list"]
    require(isinstance(items,list) and all(isinstance(item,dict) for item in items))
    matches=[i for i,item in enumerate(items) if item.get("id")==target]
    require(len(matches)==1)
    print("agents.list["+str(matches[0])+"]")' "$AGENT_ID")"
"$OPENCLAW_BIN" config set "$AGENT_PATH.model" "\"$MODEL\"" --strict-json >/dev/null
"$OPENCLAW_BIN" config set "$AGENT_PATH.tools.profile" '"minimal"' --strict-json >/dev/null
"$OPENCLAW_BIN" config set "$AGENT_PATH.tools.allow" '[]' --strict-json >/dev/null
"$OPENCLAW_BIN" config set "$AGENT_PATH.tools.alsoAllow" '[]' --strict-json >/dev/null
"$OPENCLAW_BIN" config set "$AGENT_PATH.tools.elevated.enabled" 'false' --strict-json >/dev/null
"$OPENCLAW_BIN" config set "$AGENT_PATH.tools.deny" '["group:runtime","group:fs","group:web","group:memory","group:ui","group:automation","group:messaging","group:nodes","group:agents","group:media","group:plugins","cron","gateway","session_status"]' --strict-json >/dev/null
"$OPENCLAW_BIN" config set "$AGENT_PATH.skills" '[]' --strict-json >/dev/null
"$OPENCLAW_BIN" config validate >/dev/null

echo "Oda dinner planner configured as an isolated, tool-free OpenAI agent."
