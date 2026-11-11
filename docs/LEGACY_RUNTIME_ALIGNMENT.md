# Plan: converge a legacy installation onto a reproducible release

Status: proposed follow-up, not authorization to upgrade a household. The
Ukeplan presentation backport below is deployed; the full upgrade is not.
Core's [canonical recovery guide](https://github.com/TrygveAasheim/familybot-core/blob/main/REDEPLOY.md)
remains authoritative. This plan adds release tracking and verification, not a
new architecture or a second installer.

## Root cause and observed evidence

Source promotion and household deployment were deliberately separated during
the clean-installation work. Subsequent reviewed UI builds were deployed with
the legacy API/supervisor retained. Thus aligned Git branches did not imply an
aligned installed stack. The existing one-shot receipts identify frontend
commits, but do not constitute a complete Core/API/UI/schema release manifest.

The 2026-11-11 deployment preflight correctly refused current Dev: read-only
inspection found no `familybot_schema_migrations` table. Status reported Core 0,
Portal 0, current false; this means unversioned, not an empty/lost database.
Current Portal requires validated Core 1 and Portal 2. The installed service also
relies on legacy workspace defaults. Profile and some grocery booleans are
implicit, and the PIN is at the legacy runtime path rather than the canonical
workspace path. A full upgrade must explicitly preserve those effective values.

Do not fix this by inserting migration ledger rows, relaxing startup checks,
running fresh-install seeds, or pointing the service at a new empty workspace.
The supported migration must validate/adopt existing tables transactionally.

## Bounded mitigation completed

Owner-authorized Ukeplan backport: Portal frontend `ec0f303`, replacing frontend
`786fdcf`, with the installed API, supervisor and dependencies retained. The
runtime-input diff was limited to the four Ukeplan presentation files; the lock
file was unchanged. No dinner-agent setup or database migration ran.

- Fresh lint/full Portal tests passed: 19 presentation/overview tests, 114 API
  tests, agent-setup tests, rendered contracts, build/typecheck and audits.
- Consistent SQLite backup and old frontend/service backups were retained
  privately. These are owner-only local snapshots, not claimed to be encrypted
  off-device recovery copies.
- Replacement occurred only after the managed Portal listeners stopped; the
  same LaunchAgent restarted API and web together, rotating the session token.
- Served JS/CSS, health, session and configured LAN origin checks passed.
  Four curated plan responses were compared by hash before/after, without
  publishing their contents. Schema and protected runtime/config/PIN file
  comparisons were unchanged. No household mutation endpoint was exercised.
- Physical iPad rendering and observed automatic kiosk reload remain manual
  checks. API rotation plus the existing browser reload contract is not proof
  that every physical device has reloaded.

This is an intentional temporary mixed release, not a full Dev installation.
Rollback replaces the frontend with the saved tree while the managed service
is stopped, then restarts and verifies session rotation/health. Do not restore
SQLite for this presentation-only rollback.

## Sequenced work and acceptance gates

### Authorized dry run — 2026-11-11: live upgrade blocked

The owner subsequently authorized a dry run followed by live execution only
when the acceptance gates pass. The dry run used a consistent private SQLite
copy, explicit copied configuration/PIN, and the supported installer with
`--upgrade --writers-stopped --no-deploy`. Python network connections were
disabled in rehearsal subprocesses. No credentials for external providers,
schedulers, mail readers, inference or delivery workers were started.
Selected source pair: Core `711e6b0`, Portal `ec0f303`.

| Acceptance criterion | Result |
| --- | --- |
| Preserve effective feature settings and legacy PIN in the private proposal | Prepared; legacy Oda/AI are unconditional backend capabilities, not flags in its session response |
| Supported upgrade accepts the actual legacy schema | **Failed**: `routing_audit.quarantine` is missing |
| Failed migration leaves original data/schema untouched | Passed: all 27 original tables unchanged; no new table/ledger committed |
| Supported restore recovers the snapshot | Passed: exact schema and all table rows compared by local hashes |
| Legacy API starts from the restored copy | Passed: health/session, four plan detail routes and missing-token/foreign-origin rejection |
| Upgrade preservation/migration fixture suite | 23 tests passed; those fixtures did not expose this legacy schema gap |
| Live service/configuration remain intact | Passed: web/API healthy; protected runtime/config/PIN hashes unchanged |
| New API activation, repeated upgrade, live chores and physical iPad | Not run: blocked at schema adoption |

Root cause of the dry-run failure: `CREATE TABLE IF NOT EXISTS` does not add
columns to a pre-existing table. Core's baseline validates the required
`routing_audit.quarantine` column, but its adoption path only explicitly repairs
`week_plans.layout_json`. The existing legacy audit table has no quarantine
column. Validation correctly rolls back rather than claiming migration success.

Required before another attempt: implement and review an additive legacy-schema
adoption fix in Core, with a fictional fixture reproducing the real table shape,
preservation, idempotency, validation-failure and restore regressions. Specify
the treatment of historical audit rows explicitly; do not guess that a missing
flag means a message was safely processed, and do not alter ingestion/outbox
state. Preserve existing migration checksums and keep malformed/unknown schemas
fail-closed. Then rerun the complete private rehearsal and remaining gates.
The live database was not migrated and the Ukeplan frontend backport remains
in service. Restore evidence here is a real private-copy test, not a live
rollback or physical device test.

### PR group 1 — Inventory and release identity (Core + Portal)

Extend existing setup/status tools; do not create another orchestration layer.

1. Inventory explicit workspace, database, config, PIN, runtime and service
   paths; effective profile/features; schema versions; Python/Node versions;
   source commits and hashes of installed source/build files. Inspect unknown
   deployed files instead of assigning them the current Git SHA.
2. Store an owner-only atomic deployment receipt after successful verification:
   Core commit or unmapped-file hashes, Portal API/supervisor source, frontend
   source, dependency-lock digest, schema versions, deployment mode/time and
   rollback reference. Exclude tokens, PIN values, family data and credentials.
3. Add privacy-safe status states: complete compatible release, explicit
   backport, drift, unknown. Missing receipts mean unknown, not healthy/aligned.
   Keep paths and detailed hashes in private operator output, not public APIs.
4. Integrate receipt handling with `deploy_core.sh`, `deploy-local.sh` and the
   existing installer. Publish success only after probes; failed deployments
   must not replace a previous successful receipt with a success claim.

Tests: fictional matching/mixed/missing manifests, changed files/locks,
malformed receipts, interrupted atomic write, secret exclusion and failed
health checks. Acceptance: status accurately distinguishes Git from deployment
and never claims the whole stack matches a frontend-only source SHA.

### PR group 2 — Exact legacy upgrade rehearsal (Core-owned)

Use the existing installer/migration modules and extend preservation tests.

1. Build a fictional legacy fixture from reviewed legacy schema definitions,
   not a current DB with only its ledger removed. Cover extra legacy columns,
   retained chores/rewards/history, week-plan interpretations, pending/sent
   delivery rows and ingestion state. Never commit private records or backups.
2. Resolve implicit profile/features into an explicit reviewed config proposal,
   preserving effective behavior and external-processing consent. Preserve the
   existing PIN via `--parent-pin-source`; do not generate a replacement.
3. Rehearse Core migration then Portal migration twice. Verify table contents
   by stable keys/field comparisons, not counts alone. Allow only documented
   migration changes and expected national-holiday refresh; never replace
   school-calendar data or reseed archived chores/inactive rewards.
4. Exercise migration failure, disk/backup failure, partial cross-component
   success, repeated upgrade, wrong paths, missing columns and checksum drift.
   Restore the matching legacy snapshot and prove it can start again.
5. After separate permission, repeat against a protected consistent copy of
   the actual household database with no providers, delivery, schedules or
   live writes. Keep comparisons local and report only pass/fail counts.

Acceptance: preservation and recovery pass for the exact selected source pair;
all unmapped runtime differences are resolved. Run existing Core unit/upgrade
tests, Portal full gates and hosted macOS managed install/restart/upgrade CI.
Do not infer actual-household safety from fictional CI alone.

### PR group 3 — Stage before downtime and verify the release (both repos)

The current installer applies data changes before `npm ci` and Portal build;
the deploy script can also synchronize the runtime venv before stopping the
service. Make those avoidable failure/downtime windows explicit and fix them
before the permanent rollout.

1. Resolve/build/audit the pinned source pair and Python environment in a
   separate release directory before taking the live service offline. Retain
   Node 22 for Portal; do not upgrade OpenClaw/its separate runtime here.
2. Validate the staged artifact and config without migrations or account calls.
   Preserve installed paths, origins, ports, credentials, feature choices and
   launchd schedule ownership. Optional agent setup is a separate reviewed
   action; a UI rollout must not silently rewrite model/agent configuration.
3. Require an explicit maintenance gate for all database writers. Enumerate
   actual services/manual workers, prevent restart during migration, and check
   quiescence. `--writers-stopped` alone is an operator assertion, not detection.
4. Back up immediately before migration; activate the complete staged release
   only after schema validation. Restart API/web together; verify generation
   rotation, old-token rejection, LAN/assets and read-only curated contracts.
5. On failed activation, retain diagnostic state and follow explicit matching
   source/state recovery. Do not promise an atomic transaction across two
   migration owners or silently restore over newer household writes.

Tests: build/dependency failure causes no live changes; stopped-service bundle
swap, stale sessions, interruption at every activation boundary, rollback and
feature/credential preservation. Use isolated macOS launchd jobs, never the
household service in CI. Acceptance: one traceable compatible release, safe
recovery, and no dependency installation into a running runtime.

## Owner-approved rollout after the PR gates

1. Pin the reviewed Core/Portal commits and record the current mixed release.
   Agree a maintenance window only after measured rehearsal timings. Keep the
   Ukeplan backport operating until then.
2. Preserve the actual existing paths. Save private config, credentials, PIN,
   service definitions and runtime snapshots; arrange encrypted recovery
   storage. Stop every inventoried database writer and take a fresh verified
   database backup. Never delete SQLite sidecars as a shortcut.
3. Use Core's existing `install_familybot.py --upgrade --writers-stopped` entry
   point with explicit `--workspace`, `--portal-repo`, `--portal-runtime` and
   `--parent-pin-source` where needed. Do not use `--demo`, `--seed` or
   `--replace-school-calendar` for the household. Final exact paths/commit IDs
   belong in a private runbook produced by group 1, not copied from examples.
4. Verify Core 1 / Portal 2 with schema/integrity validation, preserved records,
   service health, old-token rejection and the deployed release receipt. Core
   job replacement is a separate explicit step, with existing schedules and
   delivery state preserved; never replay a morning briefing as a smoke test.
5. Verify the real iPad child/parent/Ukeplan flows with the owner; test enabled
   integrations read-only first. Observe at least one normal scheduled cycle,
   with no duplicate notifications or reset data, before declaring convergence.
6. Re-enable normal deployment only after these gates. Main promotion remains
   a separate owner decision; aligned branches alone never close this incident.

## Risk assessment and stopping rules

Backport risk is low and limited to presentation/client refresh; the retained
legacy backend is not thereby upgraded or security-certified. Full convergence
is higher risk because configuration adoption, legacy schema validation and
multiple database writers interact. Pause on unknown runtime changes, missing
backups, unexplained data differences, migration errors or provider consent
ambiguity. No new account connection or model call is needed to resolve schema
compatibility. Report tested evidence separately from hardware/provider gaps.
