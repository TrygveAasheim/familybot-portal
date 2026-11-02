# HelloFresh Norway experiment

## Change record

- Change type: feature increment behind a feature flag.
- Problem or intent: replace Oda in the physical iPad test with the household's
  HelloFresh weekly menu, without popup-dependent login or repeated
  reauthentication.
- Evidence: HelloFresh Norway supports passwordless email login and account
  menus. The existing public Norwegian menu remains a safe disconnected
  fallback; the reviewed community MCP is not used.
- Scope and owner: Portal-only adapters in `local_api/hellofresh_norway.py` and
  `local_api/hellofresh_account.py`, curated API routes and flagged UI. Core
  ingestion, SQLite, scheduled jobs and the retained Oda implementation are
  unchanged.
- Acceptance criteria: AC-19 and AC-20 in
  `ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md`.
- Tests: passwordless correlation, redirect allowlist, restart/refresh
  persistence, owner-only file mode, curated menu/selection normalization,
  local-session authorization, callback redaction, rendered popup exclusion,
  full Portal suite and live disconnected or connected acceptance probe.
- Security/privacy: no password or browser cookie is collected. Provider tokens
  stay in `$HOME/.openclaw/credentials/hellofresh-no.json` with mode `0600` and
  never enter browser JSON, logs, Git or model context. Raw provider account
  payloads and identifiers are discarded.
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
`HelloFresh` in Oda's former navigation position and enables passwordless first
use. Oda remains in the code for rollback, but both grocery tabs are not shown
at the same time.

First use sends a HelloFresh email link. No popup is opened. A successful local
callback returns in the same window; polling also detects completion on another
device. If kiosk navigation cannot return, the full email link can be pasted
into the Portal. The one-time code is correlated with the locally initiated
email and public ID before exchange.

After login the browser receives only the week, country/locale, curated recipe
details and selected quantities. Refresh credentials are renewed server-side
and survive service or machine restarts. Status returns only `connected`,
`pending`, `automatic_return`, `credentials_local` and `read_only` booleans.

## Deliberately postponed

There are no routes for selecting or removing meals, skipping or changing a
delivery, modifying a subscription, address or payment, ordering, or checkout.
Those consequential provider writes require a separate review with explicit
confirmation, strict identifiers, idempotency where supported, read-after-write
verification and rollback guidance.
