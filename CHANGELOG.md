# Changelog

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
