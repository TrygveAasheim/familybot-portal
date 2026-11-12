# Original Ukeplan documents and independent reading

The child overview remains a compact link. The primary detail view now renders
the original school PDF locally with pinned PDF.js, preserving its tables,
columns, illustrations and wording. It has previous/next page, fit-width and
zoom controls within the existing page and back navigation. No popup, CDN,
document upload, browser PDF plugin or inference is required. Vendor worker,
font, CMap and decoder assets are built into the local release.

The displayed child/week remains the registered Core attribution; a notice
explains that a teacher's reused document heading can differ. The PDF itself is
never rewritten. Only one page is rendered at a time, with a 15 MiB input limit,
20-page limit, 12-million-pixel canvas budget and bounded load/render deadlines.
Rendering is passive: no forms, PDF JavaScript actions, embedded attachments or
annotation/link navigation. Homework hyperlinks therefore are not clickable in
this first viewer. Extracted per-page text is available as an accessibility aid;
its reading order is not a substitute for the visual table layout.

`GET /api/children/{child_id}/week-plans/{plan_id}/document` requires the exact
allowed Origin and current local-session header. It independently verifies the
child/plan relationship. Only that row's registered PDF beneath the configured
workspace's `db/attachments` can be opened. Symlink components, path escapes,
URLs, special files, oversized/non-PDF files and conflicting recorded SHA-256
fingerprints are rejected. Paths/filenames/errors never leak into responses.
Responses are `application/pdf`, `no-store`, with a fixed download filename and
sandbox/security headers. The app fetches bytes with the header and renders
them; it never places a token in a URL or embeds a raw PDF browsing context.

Original documents intentionally contain the school-provided content, including
any personal information printed in them. This explicit scoped exception does
not expose mailbox bodies, other attachments or arbitrary workspace files.
The shared trusted-LAN session is not individual child identity. Keep HTTP/LAN
residual risks from `DATA_BOUNDARY.md` in mind.

## Reading remains independent

Core ingestion, stored raw text/layout, day facts and asynchronous interpretation
are retained. Briefings can still consume stored plan text with their existing
length limits and deterministic fallback. Displaying a PDF does not mark an
interpretation accepted, trigger a retry, run a model or send a Telegram message.
Future dashboard facts still need source/day validation; this change does not
repair the semantic parser or automatically retry existing failed plans.

The secondary **Tekst fra ukeplanen** disclosure retains the existing text or
accepted interpretation and explicitly warns that extraction can lose table
relationships. Empty deterministic day cards and duplicate summaries are no
longer displayed. Missing, blocked, malformed, oversized or unsupported PDFs
show an honest error while that text remains accessible. DOCX/text-only legacy
plans use this fallback; no PDF is fabricated from flattened text.

New Core ingestion records a source fingerprint and preserves PDF line breaks.
Legacy records without fingerprints remain readable through the same confined
path checks, but cannot prove that a mutable historical attachment was never
replaced. A recorded hash mismatch requires operator investigation, not silently
showing different bytes. Back up `db/attachments` with SQLite. Source PDFs are
not recreated by database restore alone.

## Secondary text formatting

- Accepted interpretations keep their day and item order. Each day has a panel;
  consecutive categories share a heading: Lekser, Ta med / husk, Dette skjer,
  Fag og læringsmål, Beskjeder or Informasjon. Non-adjacent categories stay in
  their original position rather than moving dependent instructions.
- Weekly tasks and general information have separate panels. Legacy general
  notes remain visible when current general information is absent or empty.
- Explicit subject/section labels become headings. Supported labels include
  Norwegian school subjects, homework, reminders and weekdays, with common
  Nynorsk variants. Inline labels require a capitalized/all-caps known label
  followed by a colon; lowercase mentions in ordinary prose are not split.
  Standalone known labels and short colon-ended headings are also recognized.
- The same formatter covers fallback PDF text, interpreted items, the existing
  summary and deterministic day fields. Paragraph breaks and line breaks remain;
  lists retain order and numeric starts. Labels inside bullets get one bounded
  additional formatting pass. Unknown structure stays readable text.
- **Tekst fra ukeplanen** is a native disclosure below the PDF with a 48px
  target and visible keyboard focus. The original document is not collapsed.

No missing dates, subjects, goals or deadlines are invented. A PDF with no
explicit labels or line breaks cannot be reliably grouped semantically without
new interpretation; this formatter deliberately does not guess. It changes no
week/child attribution, API fields, ingestion or model settings. Text is escaped
by React, not inserted as raw HTML. Long text wraps; sections may grow/scroll
instead of clipping or reducing font size.

## Verification and rollback

Run `npm run lint`, `npm test` and the document-browser fixture checks. Test
multi-page navigation, zoom/fit, narrow layouts, error states and the retained
back button with fictional PDFs only. API regressions cover exact bytes,
wrong-child/parent/missing-plan lookup, missing/stale token, foreign origin,
query rejection, symlink escapes, missing/special/oversized files and changed
fingerprints. Text and interpretation endpoints must remain unchanged.

No database migration or model call is required. Deploy API, document module,
web and local PDF assets together through the managed service so session rotation
refreshes open dashboards. Rollback uses the previous code/build; never restore
household SQLite for this display-only rollback. Physical iPad acceptance is a
separate gate and must not be inferred from desktop tests.

### Repeatable fictional browser check

Start the isolated fixture from this checkout in one terminal:

```bash
node scripts/preview-ukeplan-document.mjs
```

In another terminal, use Playwright WebKit (a separate test tool, not a runtime
dependency). For a scratch installation without changing this repo's lockfile:

```bash
PDF_TEST_TOOLS=$(mktemp -d)
npm install --prefix "$PDF_TEST_TOOLS" --save-exact playwright@1.62.1
node "$PDF_TEST_TOOLS/node_modules/playwright/cli.js" install webkit
node tests/ukeplan-document-browser.mjs "$PDF_TEST_TOOLS/node_modules/playwright/index.mjs"
```

The fixture binds only `127.0.0.1:43127`, loads the actual viewer/CSS, generates
fictional two-page school tables/vocabulary and simulates missing/malformed PDFs.
It never starts Core/API, reads household config or calls providers. The browser
check covers page/zoom/fit controls, rapid plan switches, 768px/390px viewports,
fallback text, back, no popups and no external requests. Screenshots go to a
printed temporary directory. Stop the fixture with Ctrl-C afterwards. API
authorization and filesystem confinement are separately covered by `npm test`.
This fixture is not included in the production app entry points.

### Original-document verification (2026-11-12)

`npm run lint` and `npm test` passed: 21 overview/text/document component tests,
121 API tests, 4 agent-setup tests and 4 production-render/package tests, plus
typecheck, documentation, production build and dependency/security checks.
WebKit 26.5 (Playwright 1.62.1) passed the fictional browser check above; page
and narrow-layout screenshots were visually inspected. No physical iPad test
or private-document browser test was performed.

A fresh fictional Dashboard installation made with Core's installer
`--no-deploy` passed all 12 `tests/acceptance.py` HTTP/config probes against
isolated loopback API and standalone web processes. This does not certify
Bonjour, managed service restart, providers or physical hardware: the probe
correctly reports `release_ready: false`. No live household data, interpretation
retry, deployment or Telegram delivery formed part of these tests.

### Previous text-only release evidence

Run `npm run test:overview` for fictional parsing and actual component-rendering
tests, then `npm run lint` and `npm test` for the full Portal gate. Regressions
cover flattened subjects, Bokmål/Nynorsk labels, prose/date/URL negatives,
paragraphs, lists, numbered starts, HTML escaping, bounded nesting, source
immutability, day/category hierarchy and legacy general notes. Main-page source
contracts verify the formatter wiring and summary disclosure.

Browser checks should exercise portrait tablet and narrow-phone layouts,
enlarged text, keyboard disclosure and long unbroken words with fictional data.
Record simulated/browser checks separately from physical iPad acceptance.
Do not read a private household database just to construct visual test fixtures.

Verification on 2026-11-11: the full Portal gate passed, including 19 overview /
Ukeplan tests (11 new), 114 API tests, lint, typecheck, production build and
dependency/security checks. Desktop Safari displayed the real leaf components
and built CSS with fictional data in 768px and 390px frames; enlarged base text
wrapped, and the summary opened by click and closed with Space without a popup.
This was an isolated presentation fixture, not a live-data or physical iPad test.
The runtime acceptance probe, managed deployment and physical kiosk acceptance
remain outstanding for the separately authorized rollout.

No migration or reprocessing is needed: existing plans use the new display after
a separately authorized Portal deployment. Deploy through the normal supervisor
and API generation/client-refresh mechanism; do not copy only a web bundle into
production. Revert the presentation change and redeploy to roll back. Never
restore household data for a formatting-only change.
