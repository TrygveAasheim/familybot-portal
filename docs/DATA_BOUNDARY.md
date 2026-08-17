# Local data boundary

The integration prototype connects to the running FamilyBot, but it is not a
general-purpose OpenClaw administration surface.

## Network boundary

- The Python bridge binds only to `127.0.0.1` and refuses a non-local bind.
- Browser requests are accepted only from `localhost` or `127.0.0.1` origins.
- Mutations require a random, in-memory session token in a custom header.
- The portal is not deployed or connected to Sites hosting. The live SQLite
  file never leaves this Mac.

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

Writes are limited to `kanban_cards`:

- create a validated chore;
- change allowed fields or lane;
- archive by setting `archived_at`;
- restore an archived chore.

The bridge creates a consistent SQLite backup before the first mutation in each
session and appends a local audit record. It cannot trigger scheduled jobs, send
Telegram messages, edit email processing state or change OpenClaw configuration.

## Prototype separation

The source lives in `familybot-portal` on `prototype/integration`. It has not
been copied into `$HOME/.openclaw/workspace`, installed as a LaunchAgent
or enabled at login.
