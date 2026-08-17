# Familieportalen

An iPad-first family dashboard running only on the Mac mini and home LAN. The
default page is a DNB/Eufemia-inspired family overview for today's school items,
activities, weather, T-bane and FamilyBot source status. Each configured child has
one-tap child pages with large chores, durable points, concrete rewards and
completion history. Parent mode adds chores, sets goals and handles approvals.

## Home-network service

- Web: `http://familie.local:3000/`
- Bonjour: `Familieportalen._http._tcp.local`
- Child shortcuts: `/?child=<member_id>`
- LaunchAgent: `ai.familybot.portal`
- Deployed runtime: `$HOME/.openclaw/runtime/familybot-portal`
- Development source: this repository

The parent PIN is generated locally, kept outside git at
`runtime/parent-pin.txt`, deployed with owner-only (`0600`) permissions, and can
be changed by editing that source file followed by a deploy.

Household identities are loaded from the owner-readable, ignored file
`$HOME/.openclaw/workspace/config/family.local.json`. Git contains only
[`config/family.example.json`](config/family.example.json) with input
parameters; real names and delivery identifiers must never be committed.

## Data model and safety

Existing `kanban_cards` remain the shared task source used by Telegram and the
portal. The idempotent migration adds:

- `family_chore_meta` for child visibility, icon, points and approval policy;
- `chore_completions` for durable, idempotent history;
- `reward_goals` for concrete per-child progress.

The browser receives no email bodies, sender addresses, Telegram IDs, raw Spond
JSON, tokens or filesystem paths. Child writes require a short-lived local
session; administrative writes additionally require a PIN-backed parent
session. Origins are restricted to loopback and private/Bonjour LAN hosts on the
portal port. A consistent SQLite backup is created before migration and before
the first mutation in each API process.

## Develop and verify

```bash
npm run dev:family
npm run lint
npm test
python3 tests/acceptance.py
```

Acceptance criteria are in
`docs/ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md`. The measured report is written to
`tests/acceptance-results.json`; release requires 11/11.

## Deploy

```bash
bash scripts/deploy-local.sh
```

The deploy runs verification, backs up and migrates SQLite, copies the
standalone runtime out of macOS-protected `Documents`, then restarts the
LaunchAgent. Its supervisor owns the web server, API and Bonjour registration;
if any child process exits, launchd restarts the whole group.
