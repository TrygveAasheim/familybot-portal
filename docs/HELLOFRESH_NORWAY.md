# HelloFresh Norway experiment

## Change record

- Change type: guarded feature increment behind existing disabled-by-default
  feature flags.
- Problem or intent: model the household's real weekly journey: open the next
  editable box, see the selected meals first with images, inspect later weeks,
  replace or add/remove dishes, and pause or resume a week without leaving the
  kiosk browser. A follow-up adds quick meat, fish, pasta and vegetarian filters
  plus inline recipe expansion for ingredients, allergens and nutrition.
- Evidence: read-only live probes on 2026-11-02 found provider delivery weeks
  W46–W01, published menus through W49, 70 dishes with 70 reviewed CDN images
  in W46, three selected dishes identified by provider course indexes, and
  valid two-to-five-meal product options for four people. The deliveries API
  treats `rangeStart` as an exclusive boundary, so reads bracket the requested
  week and regression tests preserve that behavior. No provider mutation was
  made while discovering or verifying the contract.
- Scope and owner: Portal-only adapters in `local_api/hellofresh_norway.py` and
  `local_api/hellofresh_account.py`, named routes in
  `local_api/familybot_api.py`, and the flagged HelloFresh page. Core ingestion,
  SQLite, scheduled jobs and the retained Oda implementation are unchanged.
- Acceptance criteria: AC-19 and AC-20 in
  `ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md`.
- Tests: transient-password and credential safety; exact week bracketing;
  selected-first normalization and image allowlisting; product-size mapping;
  deterministic category classification; portion-aware, curated recipe detail;
  inline expansion and accessible filter controls;
  replacement preserving unrelated meals and add-ons; add/remove; stale-view
  rejection before provider access; exact-week pause; read-after-write
  verification; route authorization and error mapping; rendered touch UI; full
  Portal preflight; and read-only live connected probes.
- Security/privacy: the one-time password and renewable token boundary is
  unchanged. The only account writes are selected meal composition and one
  week's running/paused state. Server code derives subscription, customer,
  product and week identifiers; the browser cannot supply them. Address,
  payment, subscription-plan, servings, checkout and order placement are not
  exposed.
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
