# Maintenance review remediation — 2026-11

## Change record

- Change type: improvement and security maintenance.
- Problem or intent: remove the remaining known npm advisory, replace the
  oversized HelloFresh account module with focused boundaries, make provider
  endpoint drift fail closed, and make Python quality/security checks required
  rather than advisory.
- Evidence: the prior review found one allowlisted development advisory through
  ESLint's `minimatch` tree, a 1,338-line HelloFresh account adapter, reliance on
  unsupported provider web contracts, and no enforced Ruff/Bandit baseline.
- Scope and owner: Portal developer tooling, GitHub checks, and the Portal-owned
  HelloFresh account adapter. Core ingestion, family SQLite data and visible
  household behaviour are unchanged.
- Acceptance criteria: npm audit has zero findings without an allowlist; the
  stable `HelloFreshAccountClient` remains compatible while no focused module
  exceeds 500 lines; unreviewed provider paths are rejected before network I/O;
  the live probe is read-only/count-only; JavaScript and Python quality,
  dependency audit and high-severity security checks fail CI; CodeQL scans both
  repository languages.
- Tests: existing HelloFresh credential/read/write/route tests; a new negative
  provider-path test; status contract-version assertion; full Python unit suite;
  Oxlint React/hooks/a11y rules; Ruff; Bandit at medium severity with each
  intentional network/SQL/LAN exception justified inline; npm audit; pip-audit; docs,
  typecheck, build, rendered HTML and live acceptance.
- Security/privacy: no credential format or write authority expands. The new
  status field is a non-sensitive integer. The probe prints only booleans and
  counts and never performs a provider mutation. Provider paths are now an
  explicit fixed-origin allowlist.
- State and deployment: no database or credential migration. Deployment must
  copy all `hellofresh_account*.py` modules atomically with the facade and
  restart the Portal service from verified `dev`.
- Rollback: redeploy the preceding `dev` commit. The existing credential file
  and family database remain compatible; no state restore is required.
- Documentation: README, development guide, data boundary, HelloFresh runbook,
  deployment list and acceptance source checks are updated together.

## Assurance and residual risk

The known dependency advisory and module-size findings are removed, not waived.
Automated gates cover syntax, imports, React hooks, accessibility, dependency
advisories, high-severity Python security patterns and CodeQL analysis. The
HelloFresh implementation still depends on an unsupported provider web API;
that compatibility risk is contained but cannot be eliminated without an
official provider API. Reads are probed daily and on demand, while writes remain
manual because an automated write can change a real order.
