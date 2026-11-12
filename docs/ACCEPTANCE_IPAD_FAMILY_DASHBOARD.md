# Acceptance criteria: iPad-first family dashboard

These criteria are the release gate for the LAN dashboard. A criterion is only
marked passed when its stated checks succeed. A test LaunchAgent must be running
to measure runtime criteria. Release requires the criteria applicable to the
selected profile, with fresh evidence; disabled integrations are not mandatory.

## Critical release criteria

### AC-01 — Local network and Bonjour

- The production web service listens on the LAN, returns HTTP 200 through the
  Mac's `.local` hostname, and never depends on `localhost` in browser code.
- Bonjour advertises `Familieportalen` as an `_http._tcp` service on port 3000.
- API calls made from the `.local` web origin succeed.
- The service starts at login and is restarted if its supervisor exits.

Evidence: production HTTP/API probes, `dns-sd` discovery, LaunchAgent state.

### AC-02 — Family home and child entry without adult help

- The default first screen is a bank-like family overview: today's important
  school items, activities, weather, transport and household status are visible
  before entering a child or parent area.
- Each configured child has a large avatar/profile control on the home screen.
- A child reaches their chore view in one tap, without a password or typing.
- A child-specific URL can be saved as an iPad shortcut and reopens that child.

Evidence: iPad browser interaction and direct-link reload test.

### AC-03 — Chores are the primary child experience

- The child view leads with their reward progress and no admin/kanban language.
- Each current chore is an enormous touch card showing icon, title and points.
- A child completes an ordinary chore with one tap and receives immediate visual
  confirmation. No hover action is required.
- A rapid repeat tap cannot award the same completion twice.

Evidence: browser interaction plus database row/point-count assertions.

### AC-04 — Durable completion and history

- Completions are written to the live SQLite database, not browser memory.
- Completion state and points survive a page reload and service restart.
- The child can see recent items with title, time, points and approval state.

Evidence: API integration test, restart/reload check, database assertions.

### AC-05 — Optional parent approval

- A chore can be configured to require approval.
- The child immediately sees the points and reward progress, including for a
  completion marked for adult review.
- An authenticated parent can approve or reject it. Rejection removes the
  provisional points and reopens the chore for the child.
- A parent can also reject an ordinary auto-awarded completion after the fact.
- Child credentials cannot approve or reject a completion.

Evidence: authorization and state-transition integration tests.

### AC-06 — Concrete, live reward progress

- The view shows current/target value, percentage, a progress bar, remaining
  points/value and the concrete active reward.
- Reward units support points, Norwegian kroner and countable items.
- Progress changes immediately after an auto-awarded chore or parent approval.

Evidence: API calculations and child-browser UI assertions.

### AC-07 — Parent chores and rewards

- Parent mode is protected by a persistent, locally stored PIN.
- A parent can add a chore, assign a child, choose an icon and points, and toggle
  approval requirement without using Telegram or editing files.
- A parent can archive a chore, handle the approval queue and change the active
  reward goal.

Evidence: parent API authorization tests and iPad browser interaction.

### AC-08 — Family information is glanceable

- Transport occupies the top-left card with a large local train symbol,
  larger title and live countdown. Weather stays top-right with a larger
  forecast-derived local symbol, textual conditions and period forecasts.
  Existing card columns remain at tablet sizes; home cards are content-sized
  with compact header/section spacing. Content may grow for accessibility
  rather than clipping at 200% zoom. Clothing advice is
  absent from this card. Unknown symbols do not imply sunny weather.
- “Viktigst nå” below them combines dated events for today plus four days with
  only today's weekly routines, at most four chronologically ordered entries.
  Pauses include their final date. Matching source/routine occurrences appear
  once; different children and distinct times remain separate. Offset event
  timestamps use the configured household timezone, not the browser timezone.
- The standalone Activities card defaults off through
  `overviewSettings.showActivitiesCard`; its component and child-page activity
  view remain implemented. Ambiguous free-text schedules are not invented.
  See [the detailed rules and limitations](DASHBOARD_OVERVIEW.md).

- The same dashboard exposes today's school information, activities, weather,
  transport and household status without entering another add-on.
- Each child has a separate weekly-plan surface for school goals, homework,
  reminders and things to bring; these are not presented as reward chores.
- Missing/stale sources are labelled honestly; raw email, Spond payloads and
  internal errors are not shown to children.
- Grocery entries appear only when explicitly enabled. Dashboard needs neither
  Oda nor HelloFresh; enabled HelloFresh replaces the Oda navigation position.

Evidence: sanitized API contract tests and browser content assertions.

### AC-09 — iPad touch and responsive layout

- At 768×1024 portrait and 1024×768 landscape there is no horizontal overflow.
- Primary child actions are at least 56×56 CSS pixels; other touch actions are at
  least 48×48 CSS pixels.
- Core actions work using tap/click only and do not rely on hover.
- Essential text and status are usable at 200% browser zoom.
- With two children and two ordinary agenda entries, both home progress bars
  should be above the fold at 768×1024 and 820×1180 CSS-pixel portrait viewports
  at normal text size. Preserve symbol/font sizes and child touch targets.
  Busier agendas, enlarged text and smaller viewports may scroll; never clip
  information to enforce a one-screen layout. See the measured fixture and
  remaining physical-device checks in [the overview contract](DASHBOARD_OVERVIEW.md).

Evidence: computed-layout browser checks at both viewports and zoom.

### AC-10 — LAN security and data boundary

- Mutations require a random in-memory token valid until process restart;
  parent tokens are also replaced by the next successful parent login. Parent mutations additionally
  require a valid parent session.
- The API rejects missing/foreign origins and accepts only the exact origins in
  the canonical local configuration.
- The child-facing contract exposes no API keys, auth tokens, Telegram IDs,
  email bodies, raw Spond data or filesystem paths.
- Secrets and runtime state are excluded from git and owner-readable only.

Evidence: negative authorization/CORS tests, response scan, file-mode check.

### AC-11 — Operational reliability

- A timestamped SQLite backup is made before applying the dashboard migration.
- Migrations are idempotent and preserve existing FamilyBot tables and cards.
- Final validation and pending Portal markers commit together or roll back
  together. Status/startup reject incomplete schema and changed migration history.
- Upgrades preserve archived chores and disabled rewards. Core's full backup
  precedes all upgrade data changes; the operator stops every database user and
  preserves the installed workspace/runtime. A successful fixture run does not
  certify a running household upgrade.
- The supervisor exposes web and API health, terminates the group if one process
  fails, and lets launchd restart it.
- Existing unit tests, lint and production build pass.

Evidence: migration-twice and failed-final-validation tests, status/startup
negative tests, archived-chore/disabled-reward preservation, backup checks,
supervisor health and full suite. Record hosted managed-upgrade CI separately
from local fixture tests and actual hardware acceptance.

### AC-12 — Recurring chores

- A parent can create a weekly chore with one or more selected weekdays.
- A child can complete the recurring chore once on each selected day; a repeat
  tap on the same day cannot create another occurrence.
- The child sees a compact `completed/required` progress bar on the chore.
- Each daily completion immediately contributes its configured points, including
  points awaiting parent approval; rejecting a completion removes those points
  and reopens that day's repetition. The next weekly cycle starts at zero.

Evidence: API cycle tests, duplicate-day test, dashboard contract and rendered
child-card assertions.

### AC-13 — Child routine reset

- A parent can reset chores, points, or both for one selected child.
- Resetting chores removes the active routine without deleting historical rows.
- Resetting points starts a fresh reward cycle at zero while retaining the old
  goal and completion history.
- Reset actions require the parent session and are safe to repeat with the same
  idempotency key. Automatic backup is once before the first mutation per
  repository/API-service lifetime, not per reset or parent login. Take an explicit
  fresh Core database backup if immediate pre-reset recovery is required.

Evidence: authorization, backup, history-retention and reset idempotency tests.

### AC-14 — 30-point block achievement and surprise redemption

- A child sees the current progress toward a 30-point block; both pending and
  awarded points are included immediately, while rejected completions contribute
  zero.
- Each completed block is counted, the child-facing bar resets to the current
  remainder from 0 to 30, and a numeric count plus aggregate view retain the
  completed-block count. Calendar weeks do not affect the count.
- Parents can configure multiple surprise levels, such as 4, 8 and 12 full blocks.
- Reaching a surprise level does not reset the count; a parent can record the
  surprise as taken and reset the active counter while retaining redemption history.
- Achievement resets and surprise changes require the parent session and are
  idempotent where a reset key is supplied.

Evidence: weekly achievement repository tests, schema checks, parent controls and
child progress rendering.

### AC-15 — Family Kanban board

- A Kanban tab is available beside Parent mode, is parent-gated, and reads the
  curated active parent task list from `kanban_cards`.
- Child chores linked through `family_chore_meta` do not appear on the Kanban
  board and remain available only on the assigned child's chore page.
- The board exposes New, In Progress, Pause and Done lanes, and a parent can
  create, move or archive a task.
- Mutations require the parent session and keep archived tasks out of the active
  board. Automatic backup is once before the first mutation per repository/API
  service lifetime; later Kanban changes do not create a new snapshot.
- Done retains completed tasks and orders the newest status changes first.

Evidence: curated API route checks, lane validation, parent authorization tests,
rendered board assertions and live database ordering.

### AC-16 — Telegram child-chore interview

- The agent-facing command surface provides preview and confirmed-create
  commands for real child chores, distinct from generic parent Kanban tasks.
- Preview normalizes the child, points, repeat weekdays and approval settings
  without writing; create requires explicit confirmation.
- Creation is validated by the portal repository, backs up and audits the
  mutation, writes child-chore metadata atomically and is idempotent by key.

Evidence: core bridge command, portal CLI, repository tests, operation table and
live deployed runtime script.

### AC-17 — Full child week-plan detail

Primary view: show the registered original PDF faithfully with all pages,
previous/next and fit-width/zoom controls, retaining the in-page back button and
authoritative child/week header. No popup, CDN, model or PDF browser plugin is
required. Passive rendering must not execute PDF actions, forms or attachment
links. Verify portrait/narrow layouts, enlarged document scrolling, missing and
malformed documents, and navigation to another child's plan without stale pages.
The scoped PDF route independently enforces Origin/session and child/plan binding,
fixed-root no-symlink access, size/type limits and recorded fingerprint checks.
The original school document is the explicit attachment exception below; paths,
mail transport and unrelated attachments remain private. No database/interpretation
mutation occurs on read. Original PDF and stored reading data must remain available
independently; ingestion/Telegram must not depend on viewer availability.
The formatting criteria below apply only to the secondary **Tekst fra ukeplanen**
disclosure, never replace the original PDF. Remove empty day cards and duplicate
summaries. Unsupported/missing originals show an honest error plus retained text.

Applicable whenever the household has children: disabling or removing email
ingestion does not remove retained plans or the detail UI. Runtime probes leave
this criterion `not_run` until its presentation checks have fresh evidence.

- Monday through Friday select the current ISO week's plan for each child;
  Saturday and Sunday select the coming week's plan. A future plan arriving
  early cannot displace the current school-week plan. The previous-week label
  appears only for an actual fallback, including across ISO year boundaries.
- Core-resolved child/week metadata (including explicit parent subject
  overrides of stale PDF headings) is authoritative for the compact entry and
  detail view; Portal does not infer a different week from PDF text.
- Each child page keeps a compact Ukeplan entry with the week number and one
  clear action to open the dedicated plan page; it does not render the full
  summary inline.
- The detail view is scoped to that child’s plan, preserves the original PDF,
  and provides a “Tilbake” action to return to the child page.
- Secondary plan text is rendered as readable structured content: original line
  breaks are retained, bullet/numbered lines become lists, and clear section or
  weekday labels become headings instead of one large text blob.
- Explicit subject labels such as `Norsk:`, `Matematikk:` and `Engelsk:` become
  separate headings even inside a flattened text line or bullet. Blank paragraphs,
  numbered-list starts and instruction order are retained. Ordinary prose,
  clock times and URLs are not treated as subject boundaries.
- Interpreted days have distinct panels and consecutive category headings;
  weekly tasks and general information are separate. This text is available in
  a keyboard/touch-accessible disclosure below the PDF, without a duplicate
  summary. The compact child entry is unchanged.
- Long words wrap on narrow screens; no fixed height or clipping hides content.
  Existing source fields and child/week attribution remain unchanged, with no
  reprocessing or model call. See [formatting and tests](UKEPLAN_PRESENTATION.md).
- When a validated interpretation is available, the secondary disclosure groups
  source-backed items under weekdays and categories; otherwise it shows stored
  text. The PDF remains primary and the child overview remains a compact link.
- The JSON detail route excludes source email identifiers, attachment paths and raw
  integration payloads. When a PDF is present, plan text comes only from the
  parsed PDF context; email headers, addresses and body text are not used as a
  fallback.

Evidence: curated detail endpoint, repository test, rendered detail view and
live child navigation.

### AC-18 — Direct Oda grocery integration

Applicable only with explicit `portal.features.oda: true`. The model-specific
parts additionally require `portal.features.oda_ai: true` and external-processing
consent; otherwise direct-search fallback is the supported path.

- `Oda` is a top-level tab next to Kanban and is available to every valid local
  dashboard session without a parent PIN unless the HelloFresh physical-test
  flags intentionally replace it. Its implementation remains intact for
  rollback.
- The browser can connect the household account through Oda OAuth with state
  and PKCE, search products, load `likely_to_buy`, read/edit/clear the cart and
  open Oda's returned cart URL.
- The dinner assistant accepts a bounded Norwegian request and 1–12 portions,
  can use liked/purchased Oda recipe titles as preference signals, and renders
  named Oda recipe results with verified public Oda hero images or a local
  placeholder. Selecting a recipe opens its bounded public ingredients and
  instructions inside the Portal with a visible return button, so kiosk users
  never depend on browser chrome or popup permissions. Adding its available
  ingredients still requires a separate explicit button press.
- OAuth login uses same-window navigation rather than a popup, works in kiosk
  mode, and returns automatically to the Oda tab with a visible fallback link.
- The optional OpenAI dinner planner runs as a dedicated tool-free agent. It
  receives only the bounded dinner conversation and selected Oda recipe titles,
  returns search phrases rather than tool calls, and has a direct-search
  fallback. The Portal exposes no generic model chat or MCP proxy; only named
  Oda tools selected by the API adapter can run.
- OAuth access and refresh tokens are stored outside Git in an owner-only local
  file and are never returned to the browser or written to logs. Callback query
  values are redacted.
- Clearing the cart and disconnecting require explicit browser confirmation.
  Oda checkout and payment are never available through the Portal; final review
  and payment happen at oda.com.
- An unavailable Oda service or expired grant produces an isolated
  unavailable/reconnect state without breaking the dashboard, chores, Kanban or
  Ukeplan.

Evidence: OAuth/MCP adapter unit tests, local-session API authorization tests,
rendered UI assertions, credential permissions and production status route.

### AC-19 — Flagged read-only HelloFresh Norway experiment

- The HelloFresh tab and `?hellofresh=1` page are absent unless
  `portal.features.hellofresh` is explicitly `true`; the API independently
  rejects the route while disabled.
- When enabled, every valid local dashboard session can view and filter the
  public Norwegian weekly menu with recipe images, names, descriptions,
  preparation time, difficulty, calories, display tags, sold-out state and any
  disclosed extra charge.
- The adapter accepts only `https://www.hellofresh.no`, country `NO`, locale
  `nb-NO`, valid ISO weeks and reviewed public image hosts. Network calls and
  response sizes are bounded, and a cached fallback is visibly marked stale.
- Curated image URLs use the content-addressed local image route; the browser is
  not required to retrieve every card directly from the provider CDN.
- The public-menu adapter contains no HelloFresh username, password, account
  cookie, embedded bootstrap token, generic source payload, browser automation
  or mutation route. Account access is isolated in the separately flagged
  AC-20 adapter.

Evidence: adapter normalization, host rejection, secret-exclusion, stale-cache
and route authorization unit tests; rendered UI assertions; live flag-off or
flag-on acceptance probe.

### AC-20 — Guarded HelloFresh upcoming-box management

- `portal.features.hellofresh_account` defaults to `false` and requires the
  prerequisite `hellofresh` public-menu flag. The public-menu flag alone places
  HelloFresh in Oda's former top-level navigation position; the account flag adds
  login and bounded account operations. Oda remains implemented for rollback
  but is not shown beside HelloFresh.
- First use accepts the household's HelloFresh email and password inside the
  Portal. It never opens a popup or sends an email. The password crosses the
  trusted home LAN to the authenticated local API once, then is sent only to
  the fixed Norwegian HTTPS login endpoint through a pinned
  Chrome-fingerprinted TLS/HTTP2 transport with certificate verification and
  same-origin browser metadata. It is never stored, logged, returned, placed in
  model context or committed.
- No email-link fallback is offered. Live evidence for this account/market
  showed that the provider's nominal passwordless endpoint sends a password
  reset, so presenting it as login is a release-blocking defect.
- Access and refresh credentials exist only transiently in provider-response
  memory. The Portal stores only allowlisted opaque OAuth tokens outside Git in
  an owner-only local file; valid printable punctuation is accepted, while
  whitespace, control characters and oversized values are rejected. The tokens
  survive service restarts and are refreshed before use. Subsequent browser
  responses and logs contain no credentials. Five failed login attempts per
  client in five minutes trigger a temporary limit; successful login clears the
  attempts.
- A Cloudflare HTML challenge or non-JSON provider response is reported as a
  provider security block, not as an incorrect email or password.
- The login form remains hidden while a renewable credential exists. Temporary
  provider or network failures keep that credential for retry; only an explicit
  authentication rejection clears it and asks for email/password again.
- Status exposes only the non-sensitive provider contract version in addition
  to the existing connection/write-capability fields. Every account request is
  constrained to the fixed HelloFresh Norway origin and reviewed path shapes;
  an unknown path or path-supplied query is rejected before network I/O. The
  on-demand contract probe performs reads only and reports counts, never week
  IDs, recipe names, account identifiers or credentials.
- The first-use screen states that the Portal runs over the trusted private LAN.
  Account login must not be enabled on public or untrusted networks without
  adding local TLS.
- The connected surface opens the provider's next modifiable published week by
  default and lets the household traverse later delivery weeks. Unpublished
  weeks are visible but disabled. The selected dishes are shown first with
  reviewed HelloFresh CDN images; all other dishes follow as options. Option
  dishes can be narrowed with touch-friendly meat, fish, pasta and vegetarian
  filters derived from existing menu metadata.
- Public recipe images are registered server-side, cached outside Git and
  served locally with ETag/browser caching. The image route accepts no target
  URL, revalidates the reviewed CDN host after redirects, accepts only bounded
  image MIME/magic types, retains a valid stale image on refresh failure and
  requests a 960-pixel provider rendition before download. It prunes disk use
  to 600 images or 256 MB. Selected dish images are requested
  eagerly; remaining options stay lazy-loaded.
- A Portal-owned LaunchAgent prefetches every published upcoming menu at 04:45,
  logs counts rather than URLs/account data and remains independent of Core's
  briefing and ingestion schedule.
- Prefetch registration requires both HelloFresh flags. Each invocation checks
  current flags before creating a client or reading credentials; absent/disabled
  account consent must make zero account reads even when tokens remain on disk.
  Missing/invalid config fails closed. Disabling access does not delete tokens
  or cancel provider work that was already in flight.
- Any selected or optional dish expands in place and collapses again without
  navigation or a popup. Detail is fetched only on first expansion, then cached
  in the browser. It shows portion-matched ingredients, referenced allergens
  and nutrition. The API accepts only a validated
  recipe ID and 1–12 servings and returns a bounded allowlist rather than the
  provider payload.
- A valid dashboard session can replace one selected dish, add or remove a
  dish within provider-supported box sizes, and pause or resume one exact week.
  Every action requires explicit confirmation. Sold-out dishes, expired
  cutoffs, blocked weeks and actions not allowed by the provider are rejected.
- The browser supplies only week, requested course indexes and a state
  snapshot. The server derives account/product identifiers from a fresh read,
  preserves unrelated selected dishes and add-ons, serializes writes, rejects
  stale views, and performs exact read-after-write verification before success.
  A provider seamless downgrade is never silently accepted.
- It cannot change the base subscription, servings, address or payment, and
  cannot check out or place an order. No generic HelloFresh proxy exists.
- Disconnecting explicitly removes the local credential. Provider or auth
  failures remain isolated from the family dashboard and show a reconnect or
  unavailable state.

Evidence: transient-password exclusion from disk/responses, fixed provider URL,
negative provider-path tests, contract-version status and count-only live probe,
browser-TLS request metadata, provider challenge classification, refresh
rejection, opaque-token acceptance, unsafe-token rejection, temporary-failure
retention, restart/refresh persistence, file-mode, exact range-boundary,
selected-first/local-image-cache, category classification, curated portion-aware recipe
detail, inline expand/collapse, add-on preservation, stale-state, product-size,
replacement/add/remove and pause/read-after-write unit tests; local-session API
authorization and response secret exclusion; popup/email-flow exclusion and
rendered touch UI assertions; cache host/redirect/type/size/rendition/stale/prune tests;
scheduled-prefetch registration; read-only live connected image probe.

## Release measurement

The acceptance runner requires explicit `--workspace` and `--host` arguments.
It reports read-only runtime probes separately from complete release criteria.
Exit zero means automated probes passed; it never means 20 physical/provider
criteria passed. Unmeasured criteria remain `not_run`, disabled ones are
`not_applicable`, and measured checks are `pass` or `fail`. Use `--output` for a
privacy-safe report and `--require-release` to fail while evidence is incomplete.
The committed browser JSON is historical and is never imported as current proof.
Fresh browser screenshots/layout measurements, actual process lifecycle/CI
results and manual iPad/provider checks must identify the tested commit pair.
See [the test and review handoff](READINESS_REVIEW.md).

These 20 criteria cover the currently deployed family dashboard, its Telegram
child-chore add-on, week-plan detail view, Oda grocery tab and flagged
public-read-only and bounded account-backed HelloFresh experiments. A new
user-visible add-on such as Smart Home must
add provider failure isolation,
authorization, freshness/locality and touch-control criteria before it can be
declared supported; planned criteria live in the core repository's
`specs/SMART_HOME.md`.
