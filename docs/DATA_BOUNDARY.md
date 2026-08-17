# Local data boundary

The deployed portal presents a curated view of the running FamilyBot. It is not
a general-purpose OpenClaw administration surface.

## Network boundary

- Development defaults to `127.0.0.1`. The managed service deliberately binds
  to the LAN only when started with the explicit `--lan` flag.
- Browser requests are accepted only from the exact origins listed in
  `portal.allowed_origins` in the canonical local configuration.
- Health is readable without an Origin header for local supervision; all
  dashboard/session endpoints require an allowed browser origin.
- Mutations require a random, in-memory session token in a custom header;
  parent PIN attempts are rate-limited.
- The portal is deployed by launchd and advertised through Bonjour. It is not
  connected to public Sites hosting; the live SQLite file stays on the Mac.

## Read allowlist

`GET /api/dashboard` returns selected fields for family members, upcoming
events, Spond events, activities, chores, current week plans, school dates,
source freshness and scheduled-job state. It does not return raw week-plan text,
email sender addresses, Telegram IDs, Spond `raw_json`, message bodies, secrets
or attachments.

The bridge may inspect unlinked week-plan email summaries locally to identify a
likely grade. Only the message ID, subject, timestamps, status and inferred child
are returned to the browser.

## Write allowlist

Writes are limited to the dashboard's chores and rewards model:

- create a validated chore;
- change allowed fields or lane;
- archive by setting `archived_at`;
- restore an archived chore;
- register a child completion and approve or reject it as a parent;
- set an active reward goal.

The bridge creates a consistent SQLite backup before the first mutation in each
session and appends a local audit record. It cannot trigger scheduled jobs, send
Telegram messages, edit email processing state or change OpenClaw configuration.

## Source and runtime separation

Reviewed, non-private source lives in the `familybot-portal` repository. Deployment
creates a separate runtime under `$HOME/.openclaw/runtime/familybot-portal` and
installs `ai.familybot.portal` as a LaunchAgent. Private configuration, SQLite,
PIN, logs and backups are never copied into Git.
