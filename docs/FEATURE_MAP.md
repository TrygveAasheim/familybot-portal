# Feature map

## Supported now

- iPad-first family home with school, activity, weather, Entur and health cards;
- glanceable transport/weather row and shared relevant-event agenda; standalone
  Activities card disabled but retained; [overview rules](DASHBOARD_OVERVIEW.md);
- configured child profiles and direct Home Screen URLs;
- touch-first chores, immediate durable progress and completion history;
- weekly recurring chores with per-day progress and cycle completion;
- optional approval plus parent rejection of awarded or pending work;
- parent creation/archive, reward goals, review queue and child routine resets;
- family Kanban board with New, In Progress, Pause and Done lanes, parent-gated creation/movement/archive and newest-first Done history;
- opt-in all-user Oda grocery tab with separately opted-in bounded dinner AI, Oda
  recipe preferences, hero images and kiosk-safe in-Portal recipe details with
  return navigation, explicit add-all-ingredients actions, direct OAuth/MCP
  product search, personal suggestions, cart editing and checkout handoff;
- optional HelloFresh Norway experiment behind disabled-by-default public and
  account feature flags. It supports transient email/password first use through
  a browser-fingerprinted provider transport, persistent token-only local
  renewal, upcoming-week navigation, images, selected-first menus, guarded meal
  replacement/add/remove, per-week pause/resume and a bounded Mac-local image
  cache prefetched each morning; see
  [the experiment contract](HELLOFRESH_NORWAY.md);
- Telegram/OpenClaw child-chore interview bridge with preview, explicit confirmation and idempotent creation;
- child-specific week-plan detail view with structured full plan text, optional validated day/category interpretation, preserved line breaks and bullets, structured days and return navigation;
- [readable Ukeplan sections](UKEPLAN_PRESENTATION.md) with explicit subject
  headings, day/category panels and a disclosure for the existing summary;
- continuous 30-point block counting from pending and awarded completion points, with configurable surprise levels, parent redemption resets and a January annual summary; see [the achievement specification](WEEKLY_ACHIEVEMENTS.md);
- curated read/write API, SQLite backup, audit and idempotency;
- launchd supervision, Bonjour advertisement and local acceptance gate.
- empty-database installation through Core's guided, idempotent installer;
- explicit Core/Portal schema compatibility, transactional final schema validation,
  fail-closed startup/status, pre-migration backups and preservation-only upgrades
  (Core owns the full pre-upgrade snapshot and recovery procedure).

## Supplied by FamilyBot Core

- email ingestion and `ukeplan` PDF parsing;
- Spond events;
- calculated Norwegian public holidays and configured municipality/school calendar;
- scheduled briefings, Telegram delivery and health/freshness state.

## Explicitly not supported yet

- internet/cloud hosting of family data;
- individual child/parent accounts or remote access;
- Smart Home device control. Home Assistant, Xiaomi-first rollout, Nest and
  climate/appliance research are documented in the sibling core repository's
  `specs/SMART_HOME.md`, but are not deployed;
- HelloFresh subscription-plan, servings, address, payment, checkout and order
  management beyond the bounded meal and weekly pause controls;
- automatic chore generation from school homework;
- automatic TLS or safe direct internet exposure. The supported default is
  plain HTTP on a trusted LAN; remote access needs an authenticated VPN and TLS
  when the network is not trusted;
- guaranteed provider compatibility for unofficial Spond, hosted Oda MCP or
  the unsupported HelloFresh Norway web contract.

New features must preserve the data boundary in `DATA_BOUNDARY.md`, add an
acceptance criterion when user-visible, and avoid putting private household
state in Git.
