# HelloFresh Norway experiment

## Change record

- Change type: feature increment behind a feature flag.
- Problem or intent: replace Oda in the physical iPad test with the household's
  HelloFresh weekly menu, without popup-dependent login, password-creation
  emails or repeated reauthentication.
- Evidence: the current HelloFresh Norway web client submits email/password to
  `/gw/login` with country `NO` and locale `nb-NO`, then uses renewable account
  tokens. The existing public Norwegian menu remains a safe disconnected
  fallback; the reviewed community MCP is not used.
- Scope and owner: Portal-only adapters in `local_api/hellofresh_norway.py` and
  `local_api/hellofresh_account.py`, curated API routes and flagged UI. Core
  ingestion, SQLite, scheduled jobs and the retained Oda implementation are
  unchanged.
- Acceptance criteria: AC-19 and AC-20 in
  `ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md`.
- Tests: password non-persistence, invalid credential mapping, restart/refresh
  persistence, explicit auth-rejection cleanup, temporary-failure retention,
  owner-only file mode, curated menu/selection normalization,
  local-session authorization, response secret exclusion, rendered popup and
  email-link exclusion, full Portal suite and live disconnected or connected
  acceptance probe.
- Security/privacy: the password is accepted only in the first-use request,
  exchanged once and never stored or logged. Provider tokens stay in
  `$HOME/.openclaw/credentials/hellofresh-no.json` with mode `0600` and never
  enter browser responses, logs, Git or model context. Raw provider account
  payloads and identifiers are discarded. Because the Portal uses HTTP on the
  trusted LAN, first use must not run on an untrusted network without local TLS.
- State and deployment: both flags default off. The physical test sets
  `portal.features.hellofresh` and `portal.features.hellofresh_account` to
  `true`, then performs first-use login from the HelloFresh tab.
- Rollback: set `hellofresh_account` to `false` for the public menu, or set
  `hellofresh` to `false` to restore Oda in visible navigation. Removing the
  local credential disconnects the account; no SQLite restore is needed.
- Documentation: README, development guide, feature map, data boundary,
  acceptance contract and canonical Core configuration are updated together.

## Current test surface

The public flag exposes a curated Norwegian weekly menu. The account flag places
`HelloFresh` in Oda's former navigation position and enables transient
email/password first use. Oda remains in the code for rollback, but both grocery
tabs are not shown at the same time.

First use submits the account email and password through the authenticated local
Portal API to HelloFresh's HTTPS login endpoint. No popup or email link is
opened. The password is held only for that request and is not included in the
credential file, status response or request logs. The login route is bounded,
origin/session protected and rate limited.

After login the browser receives only the week, country/locale, curated recipe
details and selected quantities. Refresh credentials are renewed server-side
and survive service or machine restarts. Temporary provider failures retain the
credential for retry; an explicit refresh-token rejection clears it and returns
the first-use form. Status returns only `connected`,
`credentials_local` and `read_only` booleans.

## Deliberately postponed

There are no routes for selecting or removing meals, skipping or changing a
delivery, modifying a subscription, address or payment, ordering, or checkout.
Those consequential provider writes require a separate review with explicit
confirmation, strict identifiers, idempotency where supported, read-after-write
verification and rollback guidance.
