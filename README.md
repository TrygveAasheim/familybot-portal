# Familieportalen

Familieportalen is the iPad-first touch surface for FamilyBot. It runs on an
always-on Mac mini, is advertised with Bonjour and is reachable only on the home
LAN. The home screen presents school, activities, weather, transport and system
status; child pages provide large one-tap chores and reward progress; parent
mode manages chores, goals, approvals, weekly achievement surprises and the
family Kanban board.

> **Built for local family life:** the UI and chores model are reusable, while
> the included adapters can be configured for local school, activity, weather
> and transport services.

## Start here

A coding agent or session without prior context starts at
[`AGENTS.md`](AGENTS.md), followed by:

1. [Development guide and ownership map](docs/DEVELOPMENT_GUIDE.md)
2. [Local data boundary](docs/DATA_BOUNDARY.md)
3. [iPad acceptance criteria](docs/ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md)
4. [Supported/planned feature map](docs/FEATURE_MAP.md)
5. [New-session verification](docs/NEW_SESSION_VERIFICATION.md)

The sibling `familybot-core` repository owns the canonical system architecture,
configuration, reliability invariants and Smart Home specification.

## Network service

- Web: `http://familie.local:3000/`
- Curated API: port `8788`
- Bonjour: `Familieportalen._http._tcp.local`
- Child shortcut: `/?child=<member_id>`
- LaunchAgent: `ai.familybot.portal`
- Generated runtime: `$HOME/.openclaw/runtime/familybot-portal`

This repository does not contain a second family template. The single canonical
template and all installation documentation live in the sibling
`familybot-core` checkout:

- `familybot-core/config/family.example.json`
- `familybot-core/CONFIGURATION.md`
- `familybot-core/CREDENTIALS.md`
- `familybot-core/ARCHITECTURE.md`
- `familybot-core/SECURITY.md`
- `familybot-core/REDEPLOY.md`

Both services read the same owner-only local file at
`$HOME/.openclaw/workspace/config/family.local.json`.

Transport setup is documented in `familybot-core/CONFIGURATION.md`. The current
Ruter display uses Entur data and needs the family's departure StopPlace, the
exact Quay for the wanted direction, transport mode and public line number.

## Parent PIN

Create an ignored local PIN before deployment. Four to eight digits are
accepted for compatibility; six to eight random digits are recommended.

```bash
install -d -m 700 runtime
read -r -s -p "Parent PIN: " FAMILYBOT_PARENT_PIN
printf '\n'
printf '%s\n' "$FAMILYBOT_PARENT_PIN" > runtime/parent-pin.txt
unset FAMILYBOT_PARENT_PIN
chmod 600 runtime/parent-pin.txt
```

The PIN is never sent to the browser after login. Failed parent logins are
rate-limited in memory. Parent and child tokens are random and expire when the
API process restarts.

## Weekly chores and surprises

Weekly chore cycles use the selected weekdays and award points only when the
required occurrences are complete. A child reaches a full week at 30 approved
points in an ISO calendar week. Full weeks are counted once and continue across
weeks until a parent records a surprise as taken.

Parents can configure several surprise levels (for example, 4, 8 and 12 full
weeks). Recording a surprise starts a new achievement cycle for that child;
the redemption and previous cycle remain in the portal's local history. This
feature is portal-owned and does not alter FamilyBot Core's source ledgers.

## Develop and verify

Clone `familybot-core` and `familybot-portal` as sibling directories, then:

```bash
npm ci
npm run docs:check
npm run preflight
npm run dev:family
npm run lint
npm test
```

`preflight` invokes the canonical core validator and checks the ignored PIN.
The API reads curated columns only: no raw email bodies, sender addresses,
Telegram identifiers, raw Spond JSON, credentials or filesystem paths are
returned to the browser.

## Local deployment

```bash
bash scripts/deploy-local.sh
python3 tests/acceptance.py
```

Deployment runs preflight/tests first, backs up and migrates SQLite, builds an
isolated runtime outside `Documents`, installs the LaunchAgent and registers
Bonjour. Release requires every criterion in
[docs/ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md](docs/ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md)
to pass. Open dashboards detect the new API session generation after a service
restart and perform a full browser refresh automatically.

`dev` is the working branch; tested commits are fast-forwarded to `main` for
deployment. See [docs/BRANCHES.md](docs/BRANCHES.md) and
[docs/DATA_BOUNDARY.md](docs/DATA_BOUNDARY.md).
