# Familieportalen 🇳🇴

Familieportalen is the iPad-first touch surface for FamilyBot. It runs on an
always-on Mac mini, is advertised with Bonjour and is reachable only on the home
LAN. The home screen presents school, activities, weather, transport and system
status; child pages provide large one-tap chores and reward progress; parent
mode manages chores, goals and approvals.

> **Norway-first:** the UI and chores model are reusable, while the current data
> assumes Norwegian `ukeplan`, Spond, MET Norway and Entur conventions.

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

## Develop and verify

Clone `familybot-core` and `familybot-portal` as sibling directories, then:

```bash
npm ci
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
to pass.

`dev` is the working branch; tested commits are fast-forwarded to `main` for
deployment. See [docs/BRANCHES.md](docs/BRANCHES.md) and
[docs/DATA_BOUNDARY.md](docs/DATA_BOUNDARY.md).
