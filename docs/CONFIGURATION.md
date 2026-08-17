# Local family configuration

The populated configuration is machine-local household data. Its default path is:

`$HOME/.openclaw/workspace/config/family.local.json`

Never commit that file. Start from `config/family.example.json`, which is
intentionally identical in the portal and core repositories.

## Field reference

| Path | Required by | Meaning |
| --- | --- | --- |
| `schema_version` | both | Configuration format version; currently `1` |
| `family.display_name` | both | Family-facing display label |
| `family.locale`, `family.timezone` | both | Norwegian locale and Oslo time-zone defaults |
| `members[].member_id` | both | Stable integer matching `family_members.id` in SQLite |
| `members[].role` | both | `parent` or `child` |
| `members[].name`, `slug` | both | Local display name and stable non-secret key |
| `members[].age`, `grade` | core | Optional context and school email/ukeplan routing |
| `members[].avatar`, `default_reward` | portal | Child dashboard presentation and initial reward |
| `members[].telegram_target` | core | Parent Telegram recipient ID; omit for children |
| `integrations.email` | core | Mail account label and known forwarding addresses |
| `integrations.spond.groups[]` | core | Group ID, label and owning child `member_id` |
| `integrations.entur.client_name` | core | Entur client identification |
| `integrations.transport` | both | Stop place, centre-bound quay, line and labels |
| `integrations.weather` | both | MET Norway user agent and home/optional second-location coordinates |

`member_id` values are durable foreign keys. Do not renumber members after the
database has chores, rewards, plans or events.

## Required versus optional values

For the Norwegian deployment, home weather coordinates, Entur stop/quay
settings and every active family member are required. Email, Spond, Telegram and
the optional second location are needed only when their corresponding jobs are
enabled.

Delete an unused optional field or integration block. Do not leave placeholder
strings in the live file: coordinates and IDs are parsed as real values.

## Installation and validation

```bash
install -d -m 700 "$HOME/.openclaw/workspace/config"
install -m 600 config/family.example.json \
  "$HOME/.openclaw/workspace/config/family.local.json"
${EDITOR:-nano} "$HOME/.openclaw/workspace/config/family.local.json"
chmod 600 "$HOME/.openclaw/workspace/config/family.local.json"

python3 -m json.tool \
  "$HOME/.openclaw/workspace/config/family.local.json" >/dev/null
```

Before deployment, search the populated file for unreplaced template markers:

```bash
rg -n '_(NAME|ID|EMAIL|LATITUDE|LONGITUDE|GRADE|CLASS|REWARD)|FAMILY_DISPLAY_NAME|TRANSIT_' \
  "$HOME/.openclaw/workspace/config/family.local.json"
```

No output is expected.

## Overrides and secrets

`FAMILYBOT_FAMILY_CONFIG` selects another JSON file.
`FAMILYBOT_WORKSPACE` selects another workspace root; core also accepts
`OPENCLAW_WORKSPACE`.

This file contains routing identifiers but not passwords or access tokens.
OpenClaw/Telegram credentials, mail passwords, Spond authentication and the
portal parent PIN remain in separate ignored local stores with owner-only
permissions.
