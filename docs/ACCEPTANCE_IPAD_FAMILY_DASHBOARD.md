# Acceptance criteria: iPad-first family dashboard

These criteria are the release gate for the LAN dashboard. A criterion is only
marked passed when its stated automated or browser check succeeds. All critical
criteria must pass before the LaunchAgent is enabled.

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

- The same dashboard exposes today's school information, activities, weather,
  transport and household status without entering the chatbot.
- Each child has a separate weekly-plan surface for school goals, homework,
  reminders and things to bring; these are not presented as reward chores.
- Missing/stale sources are labelled honestly; raw email, Spond payloads and
  internal errors are not shown to children.
- A separate conversation entry remains available for complex questions.

Evidence: sanitized API contract tests and browser content assertions.

### AC-09 — iPad touch and responsive layout

- At 768×1024 portrait and 1024×768 landscape there is no horizontal overflow.
- Primary child actions are at least 56×56 CSS pixels; other touch actions are at
  least 48×48 CSS pixels.
- Core actions work using tap/click only and do not rely on hover.
- Essential text and status are usable at 200% browser zoom.

Evidence: computed-layout browser checks at both viewports and zoom.

### AC-10 — LAN security and data boundary

- Mutations require a short-lived session token; parent mutations additionally
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
- The supervisor exposes web and API health, terminates the group if one process
  fails, and lets launchd restart it.
- Existing unit tests, lint and production build pass.

Evidence: migration-twice test, backup check, supervisor health and full suite.

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
- Reset actions require the parent session, create a backup, and are safe to
  repeat with the same idempotency key.

Evidence: authorization, backup, history-retention and reset idempotency tests.

### AC-14 — 30-point block achievement and surprise redemption

- A child sees the current progress toward a 30-point block; both pending and
  awarded points are included immediately, while rejected completions contribute
  zero.
- Each completed block is counted, the child-facing bar resets to the current
  remainder from 0 to 30, and a tally counter plus aggregate view retain the
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
- Mutations require the parent session, create a backup and keep archived tasks
  out of the active board.
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

- Each child page keeps its compact per-day week-plan summary and offers a
  clear action to open the full free-text plan.
- The detail view is scoped to that child’s plan, preserves structured day
  details, and provides a “Tilbake” action to return to the child page.
- The full plan text is rendered as readable structured content: original line
  breaks are retained, bullet/numbered lines become lists, and clear section or
  weekday labels become headings instead of one large text blob.
- When a validated interpretation is available, the detail view groups
  source-backed items under weekdays and categories; if interpretation is
  unavailable, it falls back to the deterministic structured text.
- The detail route excludes source email identifiers, attachments and raw
  integration payloads. When a PDF is present, plan text comes only from the
  parsed PDF context; email headers, addresses and body text are not used as a
  fallback.

Evidence: curated detail endpoint, repository test, rendered detail view and
live child navigation.

## Release measurement

The acceptance runner writes ignored `tests/results/acceptance-results.json` with one record per
criterion (`pass`, `fail`, evidence, duration). Release requires **17/17 critical
criteria passed**. Browser findings that cannot be safely automated are captured
with viewport screenshots and explicitly reported rather than silently assumed.

These 17 criteria cover the currently deployed family dashboard, its Telegram
child-chore add-on and week-plan detail view. A new user-visible add-on such as Smart Home must
add provider failure isolation,
authorization, freshness/locality and touch-control criteria before it can be
declared supported; planned criteria live in the core repository's
`specs/SMART_HOME.md`.
