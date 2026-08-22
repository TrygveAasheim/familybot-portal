# Telegram child-chore interview

The Telegram/OpenClaw conversational layer can add a real child chore through
the portal-owned bridge. This is separate from the generic parent Kanban task
command: a child chore has an assigned child, points, repeat schedule and an
optional approval requirement, so it must be stored with `family_chore_meta`.

## Interview contract

The agent should collect, in order:

1. Which configured child receives the chore.
2. The chore title and optional description/icon.
3. Points from 0 to 1000.
4. Whether it is a one-time chore or repeats weekly. For weekly chores, ask
   which weekdays apply.
5. Whether a parent must approve it before points are awarded.

The agent then calls the preview command and presents the complete normalized
summary. It must wait for an explicit confirmation before calling create.

From the core repository:

```sh
python3 scripts/kanban.py chore-preview \
  --child "Child One" --title "Homework" --points 4 \
  --repeat weekly --weekdays 1,2,3,4,5 --approval

python3 scripts/kanban.py chore-create \
  --child "Child One" --title "Homework" --points 4 \
  --repeat weekly --weekdays 1,2,3,4,5 --approval \
  --confirm --idempotency-key "telegram:<conversation-id>:<turn-id>"
```

`chore-preview` never writes. `chore-create` requires `--confirm`, validates
again, creates a backup and audit record, and writes the Kanban card plus child
chore metadata atomically. The idempotency key makes Telegram retries return
the original result rather than creating a duplicate.

The bridge uses `FAMILYBOT_PORTAL_ROOT` when the core and portal repositories
are not siblings. It uses `FAMILYBOT_WORKSPACE` and `FAMILYBOT_DB_PATH` for the
same private database paths as the local portal service.
