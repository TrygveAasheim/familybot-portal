# HelloFresh Norway experiment

## Change record

- Change type: guarded feature increment behind existing disabled-by-default
  feature flags.
- Problem or intent: model the household's real weekly journey: open the next
  editable box, see the selected meals first with images, inspect later weeks,
  replace or add/remove dishes, and pause or resume a week without leaving the
  kiosk browser. A follow-up adds quick meat, fish, pasta and vegetarian filters
  plus inline recipe expansion for ingredients, allergens and nutrition.
  A performance follow-up replaces direct iPad-to-CDN card requests with a
  bounded Mac-local image cache and warms upcoming menus before the household
  opens the page.
- Evidence: read-only live probes on 2026-11-02 found provider delivery weeks
  W46–W01, published menus through W49, 70 dishes with 70 reviewed CDN images
  in W46, three selected dishes identified by provider course indexes, and
  valid two-to-five-meal product options for four people. The deliveries API
  treats `rangeStart` as an exclusive boundary, so reads bracket the requested
  week and regression tests preserve that behavior. No provider mutation was
  made while discovering or verifying the contract.
- Scope and owner: Portal-only adapters in `local_api/hellofresh_norway.py`,
  the focused `local_api/hellofresh_account*.py` modules and
  `local_api/hellofresh_images.py`, named routes in
  `local_api/familybot_api.py`, and the flagged HelloFresh page. Core ingestion,
  SQLite, scheduled jobs and the retained Oda implementation are unchanged;
  image warm-up is owned by a separate Portal LaunchAgent.
- Acceptance criteria: AC-19 and AC-20 in
  `ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md`.
- Tests: transient-password and credential safety; exact week bracketing;
  selected-first normalization and image allowlisting; product-size mapping;
  deterministic category classification; portion-aware, curated recipe detail;
  inline expansion and accessible filter controls;
  image source/redirect allowlisting, MIME and magic-byte validation, byte and
  disk bounds, cache reuse, stale fallback, local HTTP caching and scheduled
  upcoming-menu prefetch;
  replacement preserving unrelated meals and add-ons; add/remove; stale-view
  rejection before provider access; exact-week pause; read-after-write
  verification; route authorization and error mapping; rendered touch UI; full
  Portal preflight; and read-only live connected probes.
- Security/privacy: the one-time password and renewable token boundary is
  unchanged. The only account writes are selected meal composition and one
  week's running/paused state. Server code derives subscription, customer,
  product and week identifiers; the browser cannot supply them. Address,
  payment, subscription-plan, servings, checkout and order placement are not
  exposed. The public image route accepts only a server-registered hash key and
  never accepts an arbitrary URL or provider credential.
- State and deployment: `portal.features.hellofresh` and
  `portal.features.hellofresh_account` both default off. The household test
  enables both on `dev`. There is no Portal database migration.
- Rollback: set `hellofresh_account` to `false` to retain only the public menu,
  or set `hellofresh` to `false` to restore Oda in visible navigation. Removing
  the owner-only local credential disconnects the account.
- Documentation: README, development guide, feature map, configuration, data
  boundary and acceptance contract are updated together.

## Login and credential lifecycle

First use posts the account email and password once to the origin/session
protected, rate-limited local login route. The API uses a pinned `curl_cffi`
runtime to prime provider auth and sends credentials only to
`https://www.hellofresh.no/gw/login` with country `NO`, locale `nb-NO`, browser
metadata and certificate verification. No popup or email is opened. The form
clears the password and only allowlisted access, refresh and expiry fields are
persisted in `$HOME/.openclaw/credentials/hellofresh-no.json` with mode `0600`.

OAuth token values are treated as opaque, length-bounded printable values;
whitespace and control characters are rejected. Temporary provider failures
retain the credential for retry. An explicit authentication rejection clears
it and returns the first-use form. The password, email, tokens and raw account
payloads never enter browser responses, logs, Git or model context. Because the
Portal is plain HTTP on a trusted LAN, first use must not run over an untrusted
network without adding local TLS.

## Customer journey

After login the Portal asks the provider for `nextModifiableDeliveryWeek` and
shows that published week first, followed by later delivery weeks. Unpublished
weeks remain visible as "Meny kommer" but cannot be opened. A selected box shows:

- delivery date, cutoff, paused/running state, servings and meal count;
- selected dishes first, including images and selected quantities;
- all remaining dishes as replace/add options, with sold-out options disabled;
- quick filters derived locally from recipe names, cuisine and provider tags;
- an inline expandable recipe with portion-matched ingredients, allergens and
  nutrition, without leaving or opening another page;
- explicit confirmation before replace, add, remove, pause or resume.

Recipe detail is loaded only when a card is expanded and cached in that browser
session. The local API calls one fixed recipe-detail endpoint, validates the
24-character recipe ID and serving count, and returns a bounded allowlist. Raw
provider recipe/account objects, identifiers and HTML are never forwarded.
Protein add-on variants override stale vegetarian base tags, and punctuation-only
provider description placeholders are omitted.

## Provider contract monitoring

HelloFresh does not publish these Norway web-account endpoints as a supported
third-party API. That compatibility risk cannot be removed in this repository,
so the adapter treats it as a versioned, fail-closed boundary. Transport/auth,
menu projection, recipe projection and mutations are separate modules behind
the stable `HelloFreshAccountClient` facade. Before a request is constructed,
the transport rejects every path outside the reviewed allowlist; it never
accepts a browser-supplied URL. Fixture tests cover the expected response shapes
and every write remains snapshot-guarded and read back.

The daily image warm-up already exercises account weeks and published menus.
For an explicit count-only live probe, run:

```bash
npm run hellofresh:contract:check
```

The probe reports only contract version and counts. It performs no mutation and
prints no week IDs, recipe names, account identifiers or tokens. A successful
read probe cannot prove provider writes still work; those are deliberately not
tested automatically because doing so would alter the household's box.

## Local image cache

Curated menu and recipe responses replace reviewed provider CDN URLs with
`/api/hellofresh/images/<sha256>`. The frontend prefixes that route with the
local API origin, loads the selected box images eagerly and keeps option images
lazy. The route cannot be used as an open proxy: no URL parameter exists, and a
key must already map to metadata created from the existing HelloFresh CDN host
allowlist.

On a cache miss the API validates the final redirect host, response size, MIME
type and image signature before atomically storing an owner-only file beneath
`$HOME/.openclaw/cache/familybot-portal/hellofresh-images`. The browser gets an
ETag and one-week cache lifetime. A failed refresh leaves the prior valid image
available. The current image host is asked for a 960-pixel bounded rendition,
so full camera originals are never retained. Pruning keeps at most 600 images
and 256 MB, ordered by recent use.

`ai.familybot.portal-images` runs at 04:45 and asks only for published upcoming
menus. It downloads missing reviewed images with four workers, records counts
only and leaves provider/menu failures isolated from the dashboard. This is a
Portal add-on schedule rather than a Core briefing dependency.

Meal writes use the provider's full-cart contract, so the adapter re-reads the
week immediately before each action. It derives the exact course indexes,
preserves every unrelated selected meal and currently selected/preselected
add-on, selects a reviewed product option for the resulting meal count, and
writes only the requested week. A SHA-256 state snapshot rejects a stale browser
view before provider access. A process lock serializes writes, and the adapter
reads the provider again afterward; success is returned only when the selected
courses or paused state match exactly. Seamless provider downgrade is rejected
as an error rather than silently accepted.

## Deliberately excluded

The account adapter has no route for changing the base subscription, delivery
address, payment method, household identity, number of servings, checkout or
order placement. It is not a generic HelloFresh proxy. The public-menu adapter
remains a disconnected read-only fallback, and the reviewed community MCP is
not used.
