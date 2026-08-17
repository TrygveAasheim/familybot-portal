# Familieportalen 🇳🇴

> **Norway-first deployment.** This is an iPad-first, self-hosted family
> dashboard built for a Norwegian household. The UI and chores system are
> reusable, but the current data adapters assume Norwegian services and school
> conventions.

The dashboard runs on a Mac mini and the home LAN. Its default page gives the
family a glanceable view of school, activities, weather, public transport and
FamilyBot status. Each configured child has a one-tap page with large chores,
durable points, concrete rewards and completion history. Parent mode manages
chores, goals and approvals.

## Norwegian integration profile

| Area | Current assumption |
| --- | --- |
| Public transport | Entur Journey Planner, configured stop/quay IDs and Norwegian transit terminology |
| Weather | MET Norway Locationforecast, using home coordinates stored only in local configuration |
| School | Norwegian `ukeplan` email/PDF conventions and school-year data produced by FamilyBot Core |
| Activities | Spond events synchronized into the local FamilyBot database |
| Language | Norwegian Bokmål UI, dates and family-facing status text |
| Hosting | Always-on macOS host, launchd, Bonjour and a private home LAN |

Outside Norway, the chores, rewards, approvals, responsive UI and local data
boundary can be reused. Weather, transit, school-calendar and school-message
adapters need to be replaced or reconfigured.

## Development model

`dev` is the normal working branch; `main` is the tested production and
deployment branch. The lightweight promotion procedure is documented in
[`docs/BRANCHES.md`](docs/BRANCHES.md).

## Home-network service

- Web: `http://familie.local:3000/`
- Bonjour: `Familieportalen._http._tcp.local`
- Child shortcuts: `/?child=<member_id>`
- LaunchAgent: `ai.familybot.portal`
- Runtime: `$HOME/.openclaw/runtime/familybot-portal`
- Source: this repository

## Local family configuration

Real names and household identifiers are never stored in Git. Both FamilyBot
repositories carry the same placeholder template at
[`config/family.example.json`](config/family.example.json). Install it once as
the shared, owner-readable local configuration:

```bash
install -d -m 700 "$HOME/.openclaw/workspace/config"
install -m 600 config/family.example.json \
  "$HOME/.openclaw/workspace/config/family.local.json"
${EDITOR:-nano} "$HOME/.openclaw/workspace/config/family.local.json"
```

Replace every applicable uppercase placeholder. Remove unused optional
second-location fields instead of leaving placeholder strings. The portal needs
member IDs, roles, names, child avatars/grades/rewards, MET coordinates and
Entur stop/quay settings. FamilyBot Core additionally uses Telegram recipients,
email routing and Spond groups.

The complete field reference is in
[`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).

The default path can be changed with `FAMILYBOT_FAMILY_CONFIG`; the complete
workspace can be moved with `FAMILYBOT_WORKSPACE`. Neither setting makes it
safe to commit the populated file.

## Parent PIN

The PIN is a separate local secret at `runtime/parent-pin.txt` and is deployed
with mode `0600`. Create or replace it before deployment:

```bash
install -d -m 700 runtime
read -r -s -p "Parent PIN: " FAMILYBOT_PARENT_PIN
printf '\n'
printf '%s\n' "$FAMILYBOT_PARENT_PIN" > runtime/parent-pin.txt
unset FAMILYBOT_PARENT_PIN
chmod 600 runtime/parent-pin.txt
```

## Develop, verify and deploy

```bash
npm ci
npm run dev:family
npm run lint
npm test
python3 tests/acceptance.py
bash scripts/deploy-local.sh
```

Deployment builds the portal, backs up and migrates SQLite, copies the runtime
outside macOS-protected `Documents`, installs the LaunchAgent and registers the
Bonjour service. Release requires all
[11 acceptance criteria](docs/ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md) to pass.

For a clean Mac or disaster recovery, follow
[`docs/REDEPLOY.md`](docs/REDEPLOY.md). Architecture and privacy boundaries are
described in [`docs/DATA_BOUNDARY.md`](docs/DATA_BOUNDARY.md).

## Privacy boundary

The browser receives no email bodies, sender addresses, Telegram IDs, raw Spond
JSON, tokens or filesystem paths. The populated family config, SQLite database,
attachments, PIN, logs, caches and backups remain local and ignored. Child
writes require a short-lived local session; parent writes additionally require
the PIN. A consistent SQLite backup is created before migration and before the
first mutation in each API process.
