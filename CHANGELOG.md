# Changelog

Material security, user-facing and compatibility changes are recorded here.
Household data, credentials and provider responses are never included.

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
