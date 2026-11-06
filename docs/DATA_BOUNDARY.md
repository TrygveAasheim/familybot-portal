# Local data boundary

The deployed portal presents a curated view of the running FamilyBot. It is not
a general-purpose OpenClaw administration surface.

Upgrade boundary: a source update is not permission to reseed chores, reactivate
rewards, replace school dates or adopt another workspace. Core owns the explicit
stopped-writer upgrade and full pre-upgrade backup. Portal validates its owned
schema before committing migrations and before API startup. Recovery restores
the matching source/state pair; it must not expose household backup contents in
public review evidence. See Core's canonical `REDEPLOY.md`.

## Network boundary

- Development defaults to `127.0.0.1`. The managed service deliberately binds
  to the LAN only when started with the explicit `--lan` flag.
- Browser requests are accepted only from the exact origins listed in
  `portal.allowed_origins` in the canonical local configuration.
- Health is readable without an Origin header for local supervision; all
  dashboard/session endpoints require an allowed browser origin.
- Mutations require a random, in-memory session token in a custom header;
  parent PIN attempts are rate-limited.
- The portal is deployed by launchd and advertised through Bonjour. It is not
  connected to public Sites hosting; the live SQLite file stays on the Mac.

## Read allowlist

`GET /api/dashboard` returns selected fields for family members, upcoming
events, Spond events, activities, the active parent Kanban task list, child chores, compact current week plans, school dates,
  weekly achievement progress, configured surprise levels, redemption history,
  source freshness and scheduled-job state. Current plans contain only compact
  identity, week and fallback fields; full plan interpretation is fetched only
  by the scoped detail route. Monday through Friday use the current ISO week;
  Saturday and Sunday use the coming Monday's ISO week. If that plan has not arrived yet,
  the most recent prior week's plan is retained as a one-week fallback so the
  child screens do not go blank between school emails. It does not return raw
  week-plan text,
email sender addresses, Telegram IDs, Spond `raw_json`, message bodies, secrets
or attachments.

`GET /api/children/{child_id}/week-plans/{plan_id}` is the explicit child-page
drill-down for one plan. It returns that child’s full week-plan text and
structured day fields, while still excluding source email IDs, raw email
headers, addresses, attachment markers and integration payloads. When the
source email contains a PDF, the stored and displayed full text is rebuilt from
the parsed PDF context only; the email body is not a fallback.

The bridge may inspect unlinked week-plan email summaries locally to identify a
likely grade. Only the message ID, subject, timestamps, status and inferred child
are returned to the browser.

## Oda account boundary

The Oda tab calls only `https://oda.com/mcp` through the server-side
`OdaMcpClient`. There is no browser-visible bearer token, generic MCP endpoint,
or arbitrary tool-name input. OAuth uses dynamic client registration, state and
PKCE; tokens are written with mode `0600` beneath the owner-only
the configured private workspace's `credentials` directory (normally
`$HOME/.familybot/credentials`). Callback query values are redacted
from API request logs.

Oda requires explicit `portal.features.oda`; dinner AI additionally requires
`portal.features.oda_ai` and external-processing consent. All omitted flags
are false. The dinner interface has one narrower model boundary. A dedicated tool-free
OpenAI agent receives only the bounded dinner request, at most six dinner-chat
messages, the portion count and at most sixteen liked/purchased Oda recipe
titles. It receives no family dashboard facts, SQLite rows, OAuth tokens,
addresses, cart or product history. It returns search phrases only; Oda returns
the recipe records afterward. Invalid or unavailable model output falls back to
a direct Oda recipe search.

Because the MCP recipe schema has no image or recipe-detail fields, the server
can resolve a recipe's public `og:image` and schema.org `Recipe` description,
yield, category, ingredients and instructions. Fetches accept only HTTPS
`oda.com` recipe URLs, validate the final redirect target, and cap response
size, time, field lengths and list counts. Only HTTPS `images.oda.com` current
`/recipes/` or legacy `/oppskrifter/` image URLs are returned. No OAuth header
or household identifier is sent with that public page request. Failed or
malformed extraction becomes a local placeholder or limited detail state, not
an expanded proxy or user-visible integration failure.

Every valid local dashboard session may read Oda suggestions and the household
cart, search recipes and read the bounded liked/purchased recipe lists used for
preference signals. Sessions may add/remove products, add a selected recipe's
ingredients for 1–12 portions, or clear that cart. This is an explicit trusted
household policy: the Oda tab is not parent-PIN gated. The API allowlist is
limited to product/recipe search, selected suggestion/preference reads, cart
read/change/clear and OAuth connect/disconnect. It does not expose order
history, saved addresses or a generic MCP proxy. Oda checkout and payment
cannot be called through MCP; the browser receives only Oda's cart URL for
final review and payment at oda.com.

An Oda outage or expired OAuth grant returns an isolated unavailable/reconnect
state and must not affect `/api/dashboard`, chores, Ukeplan or Kanban.

## HelloFresh experiment boundary

The account status adds only the integer `provider_contract_version`; it is a
local adapter schema marker and contains no account or provider identity. The
transport accepts only the reviewed fixed HelloFresh Norway origin and an
explicit allowlist of path shapes. Query strings cannot be supplied as paths,
and subscription, week and recipe identifiers remain validated/escaped path
segments derived by the server.

`portal.features.hellofresh` defaults to `false`. The local session response
exposes only that boolean so the browser can hide the tab and route when the
experiment is disabled. The API also enforces the flag; a manually entered URL
does not bypass it.

When enabled, `GET /api/hellofresh/menu` reads only the public Norwegian
`https://www.hellofresh.no/menus` page. The adapter validates the final host,
country `NO`, locale `nb-NO`, ISO week, response size, recipe IDs and public
image hosts. It returns an allowlist of recipe name, headline, image, display
tags, preparation time, difficulty, calories, sold-out state and disclosed
extra charge. It does not return the source page, embedded application state,
bootstrap token, recipe URL, cookies or response headers.

The public adapter has no login, account cookie store or browser automation.
The separately gated `portal.features.hellofresh_account` adapter accepts one
email/password request from a valid local dashboard session, rate limited to
five failed attempts per client in five minutes. The password crosses the
Portal's plain-HTTP private-LAN boundary once and exists only in the first-use
form and transient API/provider-request memory. The API forwards it only to the
fixed `https://www.hellofresh.no/gw/login` endpoint using a pinned
Chrome-fingerprinted TLS/HTTP2 transport, same-origin browser metadata and TLS
certificate verification. It never stores, logs, returns or places the
password or email in model context or Git. Successful login clears the local
failure window. The email-link fallback is intentionally absent because live
Norwegian account testing showed that provider flow sends password-reset mail,
not a usable login link.

HelloFresh's access and refresh tokens exist transiently in provider-response
memory and are immediately allowlisted into the owner-only credential. The API
persists no provider account payload and returns status booleans only. No email
address, customer/subscription identifier or raw provider payload is stored or
exposed.

The allowlist treats OAuth token contents as opaque: values must be 8–8192
printable ASCII characters with no spaces or control characters, but are not
incorrectly restricted to JWT/base64url syntax. This accepts provider-defined
refresh-token punctuation without permitting header or log-line injection.

Renewable credentials are stored outside Git in
`$HOME/.familybot/credentials/hellofresh-no.json`, written atomically with mode
`0600`. Only fixed HelloFresh Norway endpoints are accepted. No popup is
required and no email is requested. A Cloudflare HTML challenge or other
non-JSON provider block is an
unavailable state, never an invalid-password result. Temporary provider
or network failures preserve the renewable credential for retry; only an
explicit provider authentication rejection clears it and returns the first-use
login form. The Portal itself is plain HTTP on a trusted private LAN, so the
one-time password request must not run over guest, public or otherwise
untrusted networks; deployments requiring an untrusted network need local TLS
before enabling account login.

Authenticated reads expose upcoming delivery weeks plus the same curated recipe
contract, selected quantities and total selected count. The provider's next
modifiable delivery week is the default. Recipe images are returned only from
reviewed HTTPS HelloFresh CDN hosts and are rewritten to content-addressed local
routes; no raw account identifiers are exposed.
Menu filters are derived locally from bounded names, cuisines and tags. Opening
one meal performs a read-only lookup by a validated 24-character recipe ID and
returns only bounded description, timing, portion-matched ingredients,
referenced allergens and nutrition. The browser never
receives raw recipe/account payloads, HTML or a generic provider URL.

The local image route accepts only a 64-character content-addressed key that the
server registered while curating a menu. It accepts no source URL, query-based
target or provider credential. The backing fetch revalidates the final HTTPS
HelloFresh CDN host, MIME type and image magic bytes, caps each response at 6 MB,
uses owner-only files outside Git and prunes the cache to at most 600 images or
256 MB. For the current HelloFresh image service it requests a provider-bounded
960-pixel rendition before download, rather than caching multi-megabyte camera
originals. Because the images are public recipe artwork rather than household data,
the registered-key route can be loaded by an HTML `img` element without the
custom API token; all menu, account and recipe-detail routes remain protected.
Browser responses carry an ETag and one-week cache lifetime. A valid prior image
is retained if refresh fails.

When both HelloFresh public and account features are enabled and deployed, the
Portal-owned 04:45 LaunchAgent reads published upcoming account menus, warms
their allowlisted images with four bounded workers and writes count-only logs.
It stores no menu/account payload and does not couple Core's ingestion or
briefing schedules to this optional add-on.
Every invocation reloads those flags before client construction or credential
access. A disabled/missing flag or unreadable configuration prevents account
reads, including from a stale installed job. Redeployment removes that job when
either flag is disabled. Tokens are preserved; in-flight work is not cancelled.

The bounded write allowlist contains only meal replacement/add/remove and
pause/resume for one exact ISO week. The server derives customer, subscription,
product and provider course identifiers from a fresh provider read. It validates
the provider cutoff, blocked state and `allowedActions`, rejects sold-out dishes,
preserves unrelated selected dishes and selected/preselected add-ons, and uses a
reviewed product option for the resulting meal count. A state snapshot rejects
stale browser actions before provider access, a process lock serializes writes,
and an exact read-after-write check is required before success is returned.
The UI also asks for explicit confirmation for every provider mutation.

No route changes the base subscription plan, servings, address, payment,
household identity, checkout or order placement. No generic provider proxy is
exposed. Provider/auth failure returns an isolated unavailable or reconnect
state and cannot break the family dashboard; the public menu fallback remains
read-only and explicitly marked stale.

## Write allowlist

Writes are limited to the dashboard's chores and rewards model:

- create a validated chore;
- create a validated Kanban task;
- change allowed fields or lane;
- move a Kanban task between New, In Progress, Pause and Done;
- archive by setting `archived_at`;
- restore an archived chore;
- register a child completion and approve or reject it as a parent;
- set an active reward goal.
- reset a selected child's active chore list, points cycle, or both.
- configure surprise levels for full-block achievements;
- reset a selected child's full-block achievement counter after a surprise is taken.
- create a child chore through the confirmed Telegram interview bridge.

The separate Oda allowlist permits household cart changes and local OAuth
connect/disconnect for every valid LAN dashboard session. These operations
change only the Oda account; they never write FamilyBot SQLite.

The separate HelloFresh allowlist permits selected-meal composition and one
week's paused/running state for every valid LAN dashboard session. These actions
change only the connected HelloFresh account and never write FamilyBot SQLite.
Provider subscription-plan, servings, address, payment, checkout and order
operations remain outside the allowlist.

The bridge creates one consistent SQLite backup before the first mutation in
each repository/API-service lifetime, not each browser or parent session. Later
mutations do not refresh that snapshot. Take an explicit fresh backup with
Core's `manage_database.py backup` before a reset when immediate pre-reset
recovery matters. Mutations append a local audit record. Resetting a child archives/hides active
portal chores and starts a new reward cycle; achievement resets also preserve
completed cycles and redemption history. Historical completion and reward rows
are retained. Interview creation is idempotent by confirmation key. It cannot
trigger scheduled jobs, send Telegram messages, edit
email processing state or change OpenClaw configuration.

## Planned add-on boundary

Smart Home will use a server-side provider adapter with an entity/action
allowlist. The browser will receive normalized state, locality/freshness and
explicit safe actions; it will not receive a Home Assistant token, arbitrary
entity access, raw camera credentials or a generic service-call proxy. Cameras
and consequential controls require a parent session and audit record.

Smart Home may own separate state/cache tables. It cannot reuse
`email_processing_state`, `delivery_outbox` or raw source columns. Its failure
must leave `/api/dashboard`, chores and school information available.

## Source and runtime separation

Reviewed, non-private source lives in the `familybot-portal` repository. Deployment
creates a separate runtime under `$HOME/.familybot/runtime/familybot-portal` and
installs `ai.familybot.portal` as a LaunchAgent. Private configuration, SQLite,
PIN, logs and backups are never copied into Git.
