# Readable Ukeplan sections

The child overview remains a compact link. The detail page formats existing
curated data; it does not reinterpret or rewrite the school plan.

## Layout and recognition

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
- The existing summary is retained in **Vis oppsummering**, a native disclosure
  below the main plan. It opens in place without a popup and has a 48px target
  and visible keyboard focus. The plan itself is not collapsed.

No missing dates, subjects, goals or deadlines are invented. A PDF with no
explicit labels or line breaks cannot be reliably grouped semantically without
new interpretation; this formatter deliberately does not guess. It changes no
week/child attribution, API fields, ingestion or model settings. Text is escaped
by React, not inserted as raw HTML. Long text wraps; sections may grow/scroll
instead of clipping or reducing font size.

## Verification and rollback

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

Subsequent owner-authorized rollout: the frontend was backported with a managed
API/web restart onto the existing legacy backend. Read-only plan preservation,
served assets, LAN and session-rotation checks passed; full-versioned-stack and
physical kiosk acceptance remain outstanding. See the
[deployment evidence and permanent alignment plan](LEGACY_RUNTIME_ALIGNMENT.md).

No migration or reprocessing is needed: existing plans use the new display after
a separately authorized Portal deployment. Deploy through the normal supervisor
and API generation/client-refresh mechanism; do not copy only a web bundle into
production. Revert the presentation change and redeploy to roll back. Never
restore household data for a formatting-only change.
