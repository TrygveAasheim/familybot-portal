# Changelog

## 2026-11-06 — Main publication documentation

- Publish the coordinated installation/upgrade candidate through reviewed PRs.
- Point fresh setup at both Main branches and one canonical guide; remove the
  temporary review-branch and unexplained fresh-install SHA requirements.
- Distinguish historical PR-only plans from the subsequent source promotion,
  and automated lifecycle evidence from outstanding physical/provider checks.

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
