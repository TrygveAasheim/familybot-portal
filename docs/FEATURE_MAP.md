# Feature map

## Supported now

- iPad-first family home with school, activity, weather, Entur and health cards;
- configured child profiles and direct Home Screen URLs;
- touch-first chores, immediate durable progress and completion history;
- weekly recurring chores with per-day progress and cycle completion;
- optional approval plus parent rejection of awarded or pending work;
- parent creation/archive, reward goals, review queue and child routine resets;
- approved 30-point full-week counting with configurable surprise levels and parent redemption resets; see [the weekly achievement specification](WEEKLY_ACHIEVEMENTS.md);
- curated read/write API, SQLite backup, audit and idempotency;
- launchd supervision, Bonjour advertisement and local acceptance gate.

## Supplied by FamilyBot Core

- email ingestion and `ukeplan` PDF parsing;
- Spond events;
- Norwegian/Oslo school calendar;
- scheduled briefings, Telegram delivery and health/freshness state.

## Explicitly not supported yet

- internet/cloud hosting of family data;
- individual child/parent accounts or remote access;
- Smart Home device control. Home Assistant, Xiaomi-first rollout, Nest and
  climate/appliance research are documented in the sibling core repository's
  `specs/SMART_HOME.md`, but are not deployed;
- HelloFresh/menu integration;
- automatic chore generation from school homework;
- a clean-room core database installer and complete LaunchAgent installer.

New features must preserve the data boundary in `DATA_BOUNDARY.md`, add an
acceptance criterion when user-visible, and avoid putting private household
state in Git.
