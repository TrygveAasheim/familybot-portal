# Changelog

## 2026-11-11 — Ukeplan backport and runtime alignment plan

- Subsequent authorized private-copy upgrade rehearsal found a missing legacy
  `routing_audit.quarantine` column. Migration rolled back; exact restore and
  legacy API recovery passed. Live upgrade was withheld at the failed gate;
  the working backport remains deployed. See the alignment plan's AC results.
- Separately authorized deployment of the reviewed Ukeplan frontend, retaining
  the installed legacy API/supervisor and database. Managed restart, session
  rotation, served assets, curated plan preservation and LAN probes passed.
- Full Dev runtime adoption remains pending: the installed legacy database is
  unversioned. No migration or model/agent configuration change was performed.
- Document the root cause, sequenced PR work, preservation/rollback gates and
  remaining physical-device checks in the [alignment plan](docs/LEGACY_RUNTIME_ALIGNMENT.md).

The source-only entries below describe their original publication boundary;
this entry records the later bounded Ukeplan deployment, not a full-stack release.

## Unreleased — readable Ukeplan sections

- Separate interpreted days, adjacent categories, weekly tasks and general
  information; display explicit subject labels as headings in all plan text.
- Preserve paragraphs, lists, numbered starts and instruction order, including
  flattened `Norsk: … Matematikk: …` text; never infer missing source structure.
- Move the existing summary into a native disclosure beneath the main plan.
- Add fictional parsing and actual-component HTML regressions, including unsafe
  HTML, bounded nesting and source immutability. Update AC-17 and the
  [presentation contract](docs/UKEPLAN_PRESENTATION.md).

Portal presentation only: no Core/API/schema changes, PDF replay, model calls
or household data access. Not deployed by this source change. Rollback is a
source revert followed by the normal reviewed Portal deployment and client
refresh; no data restoration is needed.

## Unreleased — OpenClaw dinner-agent setup compatibility

- Support both legacy list and current keyed agent rosters; preserve other
  agents and fail closed on unreadable or ambiguous inventory.
- Validate agent/model identifiers before filesystem or CLI actions, and deny
  `session_status` in addition to privileged groups for tool-free dinner AI.
- Deny all tool names with `*` as well, including newly introduced runtime tools;
  the minimal profile alone does not guarantee tool-free inference.
- Add fake-CLI regression coverage to `npm test`; no provider calls or household
  state access. The dashboard and non-AI groceries remain OpenClaw-independent.

No UI/API/schema change or Portal service deployment. Roll back the setup script
only if compatible with the installed OpenClaw roster; runtime downgrades require
matching backed-up OpenClaw state, not a household database restore.

## 2026-11-10 — Compact home spacing (candidate, not deployed)

- Reclaim whitespace below the menu and inside the overview cards, especially
  beneath “Viktigst nå”; reduce the gap before children's progress cards.
- Preserve text/icon sizes, child cards and tap targets. Keep content-driven
  heights and scrolling for busy agendas or enlarged text; no clipping.
- Verify two fictional children's progress bars above the fold in desktop
  Safari frames at 768×1024 and 820×1180, plus narrow-screen stacking at 390×844.
  Physical kiosk acceptance remains outstanding.

Portal CSS only; no API, database, Core or runtime changes. Revert this change
and redeploy the frontend to roll back. Acceptance/evidence are recorded in
[the overview contract](docs/DASHBOARD_OVERVIEW.md).

## 2026-11-10 — Glanceable overview (candidate, not deployed)

- Move transport to the top-left; retain weather at top-right and existing
  card minimum heights, with larger local SVG symbols and transport typography.
- Remove clothing advice from the home card only; keep forecast periods,
  timestamps and explicit stale/unavailable states.
- Combine dated calendar/Spond events and today's scheduled routines under
  “Viktigst nå”, deduplicate matching occurrences and retain distinct times and
  children. Disable the separate Activities card through a source display flag.
- Add fixture tests for date windows, day/time parsing, pauses, alternate weeks,
  duplicate precedence, timezone/DST and weather-code classification.

No API/schema change, Core change, live data access or deployment. Revert the
source change and use the normal reviewed deployment with client refresh to
roll back; no database restore is necessary. Free-text limitations and evidence
are documented in [the overview contract](docs/DASHBOARD_OVERVIEW.md).

## 2026-11-06 — Main publication documentation

- Publish the coordinated installation/upgrade candidate through reviewed PRs.
- Point fresh setup at both Main branches and one canonical guide; remove the
  temporary review-branch and unexplained fresh-install SHA requirements.
- Distinguish historical PR-only plans from the subsequent source promotion,
  and automated lifecycle evidence from outstanding physical/provider checks.
- Correct Main deployment policy, backup cadence, provisional points, numeric
  block counts, HelloFresh flags/token storage and planned Smart Home wording.

No runtime deployment, schema change or household data access is part of this
publication. Existing installations do not update themselves on a GitHub merge.
Source-only rollback reverts the paired promotion; no database restore is needed
unless an operator separately ran an installation or upgrade. Historical entries
below retain their original candidate status.

## 2026-11-06 — Upgrade preservation fixes (candidate, not deployed)

- Put all pending Portal DDL, markers, data initialization and final validation
  inside one transaction. A failed final check cannot leave current markers.
- Validate required owned tables/columns, contiguous Portal history/checksums,
  Core version, foreign keys and SQLite integrity in both status and API startup.
- Validate every consumed Core table/column before Portal migration/status/API
  startup; a Core version marker alone must not conceal a missing calendar table.
- Deployment no longer repairs deliberately deactivated rewards. Explicit
  starter seeding respects archived matching chores; Core upgrades do not seed.
- Add rollback/status/startup/history/archived-chore regressions; coordinate
  with Core's full pre-upgrade snapshot, explicit runtime and recovery procedure.

No new schema version or live deployment. For source-only rollback revert the
paired change. If household data must be rolled back after an attempted upgrade,
stop every database user and follow Core's `REDEPLOY.md` with the full pre-upgrade
snapshot and matching source/configuration; a Portal-only backup can be too late.

## 2026-11-06 — Double-review follow-up (candidate, not deployed)

- Keep Ukeplan presentation acceptance applicable for households with children,
  even when email ingestion is absent/disabled; retained plans remain viewable.
- Require both HelloFresh public and account flags before registering the image
  job and before any client/credential access on each invocation. Missing config
  fails closed; disabling access preserves tokens without using them.
- Add persisted disabled-email/retained-plan tests and prefetch consent,
  registration and missing-config regressions using fictional data and mocks.

No schema change or deployment. Revert the source commit for rollback; no
database restore is needed. Reverting the consent guard reintroduces that risk.

## 2026-11-06 — Installation review fixes (candidate, not deployed)

- Use `.familybot` consistently while preserving explicit legacy overrides.
  API database/PIN and provider credential/cache defaults follow the selected
  household; another ambient workspace cannot redirect provider state.
- Create missing per-user deployment directories and require a GUI launchd
  domain before replacing services. Disposable CI supports unique labels/paths.
- Avoid reverse-DNS lookup during API socket binding: unavailable host DNS must
  not block local health/startup. Configured browser-host verification remains.
- Require explicit Oda and Oda AI flags, with separate external-model consent.
- Replace the owner-specific acceptance runner with explicit-target read-only
  probes, configurable household/reward checks and honest unmeasured criteria.
  Historical browser results never count as fresh acceptance evidence.
- Isolate API fixture tests from inherited household configuration, including
  when the deploy script runs the source test suite.
- Reconcile README, configuration, security boundaries, grocery, release and
  testing Markdown; see `docs/READINESS_REVIEW.md` for the separate hardware gate.

No schema change, merge or runtime deployment. Roll back with the coordinated
source pair, not a database restore. Existing configurations that omitted Oda
flags must explicitly enable wanted capabilities before a later upgrade.

Material security, user-facing and compatibility changes are recorded here.
Household data, credentials and provider responses are never included.

## 2026-11-05

### Independent dashboard installation

- Added versioned Portal schema migrations with a shared component/checksum
  ledger, explicit Core schema compatibility and verified pre-migration backup.
- Made an empty Core database a supported starting point through the sibling
  guided installer; fictional demo data now covers chores, approval, restart
  and upgrade without private household state.
- Made Oda, Oda AI, HelloFresh and its image job disabled-by-default features.
  Disabled providers no longer appear in navigation or execute provider/model
  calls, and a later profile downgrade removes provider-only Python packages.
- Added configurable family name, locale/time-zone clock data and
  profile-aware process status. Missing weather/transport and provider outages
  degrade independently from the dashboard.
- Moved the canonical parent PIN and new-install provider/cache state beneath
  the private FamilyBot workspace while retaining explicit legacy overrides.

Portal now requires Core schema version 1 and Portal schema version 2. Existing
data remains compatible and is backed up before migration. Roll back source and
restore the generated pre-migration database with Core's supported restore
command if needed.

### Dependency maintenance

- Updated React type definitions to the React 19.3 line.
- Aligned the direct Tailwind CSS dependency with the existing 4.3.3 PostCSS
  integration.
- Updated `curl-cffi` to 0.17.0, including refreshed, hash-locked wheels used by
  the HelloFresh integration.
- Directed future Dependabot pull requests to the `dev` integration branch so
  dependency changes follow the documented review and deployment flow.

These dependency-maintenance changes add no further database or credential
migration. Deployment rebuilds the Node.js bundle and Python runtime
environment from the committed lock files.

## 2026-11-03

### Security and quality hardening

- Aligned Ruff with the supported Python 3.12 runtime.
- Updated the security policy to match the enforced Ruff, Bandit, pip-audit,
  npm-audit and dual-language CodeQL gates.
- Added reproducible, hash-locked Python runtime and CI security-tool dependency
  sets and restored full transitive dependency auditing.
- Removed stale documentation for the retired `minimatch` exception and audit
  wrapper; the current dependency graph has no open advisory.

There is no Portal runtime, database or credential migration. The deployed UI
and API behaviour are unchanged.
