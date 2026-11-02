# HelloFresh Norway experiment

## Change record

- Change type: feature increment and login bug fix behind a feature flag.
- Problem or intent: replace Oda in the physical iPad test with the household's
  HelloFresh weekly menu, without popup-dependent login, password-creation
  emails or repeated reauthentication.
- Evidence: the current HelloFresh Norway web client submits email/password to
  `/gw/login` with country `NO` and locale `nb-NO`, then uses renewable account
  tokens. A server-side reproduction returned a Cloudflare 403 HTML challenge
  before checking credentials, while the Portal collapsed that response into
  “wrong password.” The refresh endpoint remained available. The existing
  public Norwegian menu remains a safe disconnected fallback; the reviewed
  community MCP is not used.
- Scope and owner: Portal-only adapters in `local_api/hellofresh_norway.py` and
  `local_api/hellofresh_account.py`, curated API routes and flagged UI. Core
  ingestion, SQLite, scheduled jobs and the retained Oda implementation are
  unchanged.
- Acceptance criteria: AC-19 and AC-20 in
  `ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md`.
- Tests: password exclusion from the local API, browser bootstrap/completion,
  Cloudflare challenge classification, restart/refresh persistence, explicit
  auth-rejection cleanup, temporary-failure retention, owner-only file mode,
  curated menu/selection normalization, local-session authorization, response
  secret exclusion, rendered popup and email-link exclusion, full Portal suite
  and live disconnected or connected acceptance probe.
- Security/privacy: the browser exchanges the password directly with the fixed
  HelloFresh HTTPS endpoint; the password never reaches Portal code outside the
  first-use form and is never stored or logged. Provider tokens exist briefly in
  browser memory, are allowlisted into the authenticated completion request and
  then stay in `$HOME/.openclaw/credentials/hellofresh-no.json` with mode
  `0600`. They do not enter later browser responses, logs, Git or model context.
  Raw provider account payloads and identifiers are discarded. Because the
  Portal uses HTTP on the trusted LAN, first use must not run on an untrusted
  network without local TLS.
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

First use obtains a public guest bootstrap token through the authenticated local
Portal API, then the browser submits the account email and password directly to
HelloFresh's HTTPS login endpoint. No popup or email link is opened. The local
API never receives the password. The browser posts only the returned access,
refresh and expiry fields to the completion route, clears the password field and
does not persist the tokens. The bootstrap route is origin/session protected
and rate limited. HTML security challenges and other non-JSON provider blocks
remain unavailable states rather than being labelled invalid credentials.

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
