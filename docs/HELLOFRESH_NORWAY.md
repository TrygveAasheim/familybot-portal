# HelloFresh Norway experiment

## Change record

- Change type: feature.
- Problem or intent: evaluate whether HelloFresh can eventually complement or
  replace the household's Oda workflow without first entrusting credentials to
  an unproven community MCP server.
- Evidence: HelloFresh publishes a public Norwegian weekly menu, while the
  reviewed community MCP implementation was US-specific and did not meet the
  project's credential-confidence threshold.
- Scope and owner: Portal-only optional add-on in
  `local_api/hellofresh_norway.py`, its curated API route and the flagged UI.
  Core ingestion, SQLite, Oda and scheduled jobs are unchanged.
- Acceptance criteria: AC-19 in
  `ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md`.
- Tests: recorded public-page-shaped fixtures, Norwegian locale/country
  validation, host and secret exclusion, stale-cache behaviour, local-session
  authorization, rendered UI, full Portal suite and live public-menu smoke
  read.
- Security/privacy: no HelloFresh login, username, password, cookies or account
  state. Only an allowlisted subset of a bounded public Norwegian menu page is
  returned to a valid LAN dashboard session.
- State and deployment: no migration or durable state. The experiment defaults
  off and is enabled with `portal.features.hellofresh: true` in the ignored
  canonical household config, followed by a normal Portal redeploy.
- Rollback: set the flag to `false` and redeploy, or revert the Portal source
  commit. No HelloFresh or SQLite state needs restoration.
- Documentation: README, development guide, feature map, data boundary,
  acceptance contract and canonical Core configuration are updated together.

## Current test surface

When enabled, `HelloFresh` appears as a top-level tab without replacing `Oda`.
It reads the public `https://www.hellofresh.no/menus` page and shows the active
Norwegian menu in a touch-friendly grid. The browser can filter the already
loaded menu by recipe name, description or display tag.

The adapter extracts only:

- week, country and locale;
- recipe identifier, position, name and headline;
- reviewed public image URL;
- preparation time, difficulty, calories and display tags;
- sold-out state and disclosed per-portion extra charge.

The source page's application payload, public bootstrap token, cookies, headers
and recipe URL are discarded. Fetches have a timeout and size limit. A good
menu is cached for 15 minutes; if a later provider read fails, it may remain
available for up to six hours with an explicit stale warning.

## Deliberately postponed

Do not add account authentication by extending the public-page parser. Account
work requires a separate security review covering HelloFresh's terms, Norwegian
login/session behaviour, password avoidance, encrypted owner-only session
storage, browser sandboxing, confirmation for every consequential action,
strict identifiers and read-after-write verification.

Until that review is accepted, there are no tools or routes for selecting
meals, skipping weeks, changing deliveries, modifying a subscription, ordering
or paying.
