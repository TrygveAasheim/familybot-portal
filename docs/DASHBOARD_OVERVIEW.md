# Glanceable dashboard overview

## Layout and relevance contract

Transport is top-left, weather top-right, and the combined “Viktigst nå” agenda
spans the next row. The layout keeps two equal columns on tablets, then stacks
on narrow screens. Home cards are content-sized rather than reserving a minimum
height. Compact header/section spacing brings children's progress higher without
shrinking the icons, fonts, child cards or touch targets. The agenda date column
has room for date/time wrapping instead of wasting vertical space. Content can grow at large
text sizes instead of being clipped. The train symbol and weather artwork are
local vectors; temperature/conditions remain readable text. The forecast-derived
weather symbol replaces the fixed emoji. Clothing advice is hidden only here,
not removed from Core, briefings or the API. Stale weather is explicitly labelled.

`app/_components/dashboardOverview.ts` owns presentation rules:

- Dated calendar and Spond events: today and the following four days.
- Recurring activities: today only, using the API's household date. A routine
  is not displayed throughout the week just because it exists.
- Recognized schedules: Norwegian weekday names, singular/plural, optional
  `HH:MM`/`HH.MM` times, multiple weekday clauses, and explicitly odd/even
  alternate weeks. A paused-until date is inclusive.
- Unknown dates, unspecified alternate weeks, date ranges and recognizable
  monthly/exception prose are not guessed. A weekday without a time stays
  untimed. This is a deliberately limited parser, not natural-language calendar
  interpretation. Notes outside the curated schedule are not read; exceptions
  should be represented by a pause or corrected dated source data.
- Offset timestamps are normalized to the configured household timezone before
  comparison. Date-only values are handled as calendar dates, including DST and
  year boundaries, without browser-timezone date arithmetic.
- Duplicate dated records share normalized title, member, household date and
  time. Spond wins an otherwise identical tie. An untimed duplicate can be
  replaced by a single unambiguous timed occurrence. Different times/children
  are retained.
- A dated occurrence suppresses a routine with the same member/date, compatible
  time and matching title (including a title prefix or an explicit parenthesized
  schedule label such as “samspill”). Unrelated titles are not merged merely
  because a child, time or place matches. Truly different source titles without
  such evidence may still appear twice; fix source attribution rather than
  hiding a potentially separate appointment.
- The agenda retains its four-entry bound, ordered by date/time/title. Further
  entries are not deleted. It is a glanceable selection, not a full calendar.

`overviewSettings.showActivitiesCard` defaults to `false`. Set it to `true` and
rebuild through the reviewed deployment workflow to restore the standalone card.
This is a source presentation flag, not a new per-household configuration field.
Child pages and their existing activity lists are unchanged.

## Change record and verification

- Type/intent: UI improvement requested to reduce duplicate information and make
  weather/transport legible from a distance.
- Scope/owner: Portal presentation only. No database migration, private data
  access, provider calls, new browser fields or Core changes.
- Acceptance: AC-08 and AC-09; large truthful symbols/countdown, stable tablet
  columns, reversible Activities hiding, date-scoped and deduplicated agenda.
- Tests: `npm run test:overview`, `npm run lint`, `npm test`. Fixtures cover
  schedule/day/time, pauses, alternate weeks, five-day bounds, timezone/DST,
  distinct appointments and weather symbols. API tests continue unchanged.
- Security: React text escaping and local SVGs; no arbitrary image URLs, model
  use, raw provider payloads, new permissions or writes.
- Deployment: not implied by source changes. Use the existing reviewed deployment
  and session-generation browser refresh, preserving the installed workspace.
- Rollback: revert the source change and redeploy; no household database restore.
- Manual evidence: physical iPad, 200% zoom and live provider acceptance must be
  measured separately; fixture/build success does not certify those checks.

### Candidate verification, 2026-11-10

114 Python API tests, 8 overview tests and 2 rendered/source-contract tests
passed, together with TypeScript, production build, docs, lint, Bandit and
dependency audits. A desktop Safari preview used entirely fictional in-memory
data on loopback ports, with no household database or provider access. Visual
inspection confirmed transport/weather positions and larger local symbols,
absence of clothing advice/standalone Activities, one displayed music occurrence
despite three matching inputs, and omission of a different-day routine. The
temporary preview servers and tab were stopped afterward. Exact iPad dimensions,
200% zoom and physical touch acceptance remain unverified. No live deployment
or runtime acceptance probe was performed.

### Compact-spacing follow-up, 2026-11-10

The follow-up changes only home-scoped CSS, tests and documentation. It removes
the large header/card minimum heights and auto-pushed holiday footer, reduces
card padding and the gap before children's cards, and gives dates a wider column.
No information, fonts, symbols, child-card dimensions or interaction targets are
removed or reduced. Other tabs and the agenda selection rules are unchanged.

A desktop Safari preview rendered the actual dashboard with a fictional,
read-only loopback API in fixed-size frames. The fixture had two children with
12/30 points, two timed activities with school locations, a holiday footer,
three forecast periods and live-style departure times. Measured results:

| CSS viewport | Bottom of both progress bars | Horizontal overflow |
| --- | --- | --- |
| 768×1024 | 1011px (both visible) | None |
| 820×1180 | 1013px (both visible; entire child cards also fit) | None |
| 390×844 | Below fold; expected single-column scrolling | None |

These are desktop browser layout measurements, not physical iPad acceptance.
At 768×1024 the arrows/bottom of the child cards still extend below the fold.
More/longer events, more children, enabled navigation items, browser chrome and
larger text can require scrolling; content must never be hidden to force a fit.
The new source-contract test guards spacing, home-only scope and the absence
of clipping/font-size changes; it does not replace browser geometry checks.
`npm run lint` and `npm test` passed: 114 Python API tests, 8 overview tests,
3 rendered/source-contract tests, docs, TypeScript, production build, Bandit
and dependency audits. No live API or household database was used.
Confirm on the household kiosk after a separately approved deployment. Rollback
is a CSS revert and frontend redeploy, with no database or Core change.
