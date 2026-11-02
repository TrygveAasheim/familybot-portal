# HelloFresh Norway experiment

## Change record

- Change type: feature increment and login resilience fix behind a feature flag.
- Problem or intent: replace Oda in the physical iPad test with the household's
  HelloFresh weekly menu, without popup-dependent login, password-creation
  emails or repeated reauthentication.
- Evidence: the current HelloFresh Norway web client submits email/password to
  `/gw/login` with country `NO` and locale `nb-NO`, then uses renewable account
  tokens. The direct cross-site Portal request was blocked by Cloudflare before
  credentials were checked, while first-party phone login worked. The attempted
  provider passwordless flow then sent a password-reset email rather than a
  login link, so that fallback was removed. A maintained third-party HelloFresh
  integration documents the same TLS/HTTP2 fingerprinting boundary and uses
  `curl_cffi` Chrome impersonation plus same-origin browser headers. The Portal
  now applies that bounded pattern only to the fixed provider login endpoint.
  The existing public Norwegian menu remains a safe disconnected fallback; the
  reviewed community MCP is not used.
- Scope and owner: Portal-only adapters in `local_api/hellofresh_norway.py` and
  `local_api/hellofresh_account.py`, curated API routes and flagged UI. Core
  ingestion, SQLite, scheduled jobs and the retained Oda implementation are
  unchanged.
- Acceptance criteria: AC-19 and AC-20 in
  `ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md`.
- Tests: transient password exclusion from disk and responses, fixed provider
  URL, Chrome TLS request metadata, Cloudflare challenge classification,
  invalid-credential classification, restart/refresh persistence,
  explicit auth-rejection cleanup, temporary-failure retention, owner-only
  file mode, curated menu/selection normalization, local-session authorization,
  response secret exclusion, rendered popup exclusion, full Portal suite and
  live disconnected or connected acceptance probe.
- Security/privacy: the password crosses the trusted-LAN HTTP hop to the local
  API once and is forwarded only to the fixed HelloFresh HTTPS endpoint using a
  pinned Chrome-fingerprinted transport with certificate verification. It is
  never stored, logged, returned or placed in model context. Provider tokens
  exist briefly in response memory, are allowlisted and then stay in
  `$HOME/.openclaw/credentials/hellofresh-no.json` with mode `0600`.
  Credentials do not enter later browser responses, logs, Git or model context.
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
email/password first use. Oda remains in
the code for rollback, but both grocery tabs are not shown at the same time.

First use posts the account email and password once to the origin/session
protected, rate-limited local login route. The API uses `curl_cffi==0.16.3` in
an isolated Python 3.12 runtime, matching its Chrome version in the TLS/HTTP2
fingerprint and request headers. It primes the provider auth session and sends
credentials to `https://www.hellofresh.no/gw/login` with country `NO` and locale
`nb-NO`. No popup or email is opened. The password field is cleared after the
request, and only validated access, refresh and expiry fields are persisted.
HTML security challenges and other non-JSON provider blocks remain unavailable
states rather than being labelled invalid credentials.

There is deliberately no passwordless fallback. Provider behavior observed in
the physical test sent a password-reset email, so retaining that button would
misrepresent a recovery flow as authentication.

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
