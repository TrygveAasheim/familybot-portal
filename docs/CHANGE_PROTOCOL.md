# Portal change protocol

This repository follows the shared change-record standard in
`familybot-core/docs/CHANGE_PROTOCOL.md`. Apply the same method to every bug
fix, new feature and improvement, including documentation-only changes. A fork
may choose its own branch and release workflow, but should retain the evidence,
acceptance and rollback record.

## Required change record

Record these fields in the pull request, issue or commit description:

```text
Change type: bug fix | feature | improvement | documentation
Problem or intent: what user/system behaviour changes and why
Evidence: reproduction, failing test, log, acceptance gap or design reason
Scope and owner: API, UI, data contract, Core dependency or runtime boundary
Acceptance criteria: observable conditions that define “done”
Tests: focused regression tests plus the full Portal suite and acceptance checks
Security/privacy: response fields, inputs, authorization, logs and trust assumptions
State and deployment: migrations, backup, rollout, service and browser refresh
Rollback: source commit and any database/state restore needed
Documentation: README/spec/acceptance/data-boundary/runbook files updated
```

## Portal-specific gates

- A child-facing or parent-facing change extends
  `docs/ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md` before release.
- A new browser field or route gets an explicit allowlist/privacy review in
  `docs/DATA_BOUNDARY.md` and negative authorization coverage where relevant.
- A Core-owned fact is fixed in `familybot-core`; Portal consumes the curated
  contract and does not patch ingestion, delivery or raw source data.
- A UI and API change is tested together. Do not verify only the detail route
  when the family overview or child page also presents the same fact.
- Run `npm run docs:check`, `npm run lint`, `npm test` and
  `python3 tests/acceptance.py`; deploy only from verified `dev`.

## Worked Ukeplan example

The Ukeplan fix is the model for a cross-repository change. Core detects plans
from message content even when the email subject is blank, persists PDF-backed
facts before terminal processing, derives weekday dates from a valid ISO week,
and records a retryable validated interpretation. Portal exposes only the
accepted interpretation in the curated dashboard response and renders it on
both the child overview and full-plan page. The regression must verify both
surfaces, both children/member mappings and the deterministic fallback when
interpretation is pending or failed.

The full incident contract and Core-side safeguards are documented in the
Core repository at `docs/UKEPLAN_INTERPRETATION.md`.
