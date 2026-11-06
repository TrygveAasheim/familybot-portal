# Installation candidate: review and test handoff

The coordinated plan and F1–F8 finding matrix live in Core's
`docs/READINESS_FIX_PLAN.md` on the same candidate branch. Read the checked-out
Core `GETTING_STARTED.md` for the canonical installation commands. Both PRs
target `dev`; stop at reviewed PRs, with no merge or deployment to the existing
household. Public `main` is not yet the installer release.

## Portal changes and compatibility

- Workspace defaults consistently use `.familybot`. Explicit
  `FAMILYBOT_WORKSPACE` wins over legacy `OPENCLAW_WORKSPACE`; no discovery or
  copying of legacy state occurs. `FAMILYBOT_PORTAL_RUNTIME` retains an explicit
  old runtime path when required.
- Omitted grocery flags are disabled. Existing users wanting Oda must explicitly
  set `oda: true`; AI additionally requires `oda_ai: true` and external processing
  consent. No provider capability is installed as part of Dashboard.
- Deployment creates a missing LaunchAgents/log directory and checks the GUI
  launchd domain before stopping services. Default labels are unchanged. The
  `FAMILYBOT_PORTAL_LABEL` and `FAMILYBOT_LAUNCHAGENT_DIR` overrides exist for
  isolated disposable CI; do not point test jobs at a live runtime or ports.
- API CLI derives database and PIN from its selected workspace, unless those
  paths are explicitly supplied. No schema version changes are required.
- API socket binding does not reverse-resolve the host name. Local DNS outages
  must not block API startup; the installer still verifies the configured URL.

## Evidence, not inferred acceptance

Run source tests without private state:

```bash
npm ci
npm run lint
npm test
```

`npm test` runs Python fixtures through `scripts/test_api.py`, which strips
inherited FamilyBot config/database/provider overrides and supplies a temporary
workspace. Deployment's configured household must never become unit-test data.

On an explicitly selected test installation only:

```bash
python3 tests/acceptance.py --workspace /exact/test/workspace --host TEST-MAC.local
```

This command performs read-only FamilyBot identity/session/dashboard, feature,
permission and authorization probes. It requires `--allow-integrations` if
dashboard reads could contact configured external adapters. It never probes
grocery-provider routes or reads provider credential contents. Exit zero means
only `automated_checks_ok`, not full release readiness. `--require-release`
returns nonzero while full acceptance evidence remains outstanding. There is
deliberately no import of `tests/browser-acceptance.json`: that is historical
evidence, not a current test. Results distinguish `pass`, `fail`,
`not_applicable` and `not_run`; full browser, restart and provider criteria need
their separately recorded evidence.

Core's process lifecycle suite initializes fictional data with authoritative
migrations and tests actual HTTP parent login, chore completion/approval and
restart persistence. Its macOS managed-install job runs the full installer,
web build, plist registration and restart on a disposable hosted runner only.
Neither is a physical iPad/router test.

## Owner's separate hardware gate

Record both Git SHAs, macOS/iPadOS versions and timestamp. With fictional data:

1. Install in a new Mac account/machine using the paired PR commits.
2. Open the printed hostname on the Mac and an iPad on the same trusted LAN.
3. Save a Home Screen shortcut; reload it and enter each child without typing.
4. Check portrait/landscape, 200% zoom and large touch targets.
5. Create a parent-approved chore, complete as child, approve/reject as parent.
6. Restart/reboot; verify retained points and refreshed browser sessions.
7. Exercise documented backup/restore only on this disposable household.
8. Enable each optional integration separately, only with explicit consent.

Capture no PINs, provider credentials or private family content in public
evidence. Plain HTTP, shared LAN trust, provider contracts and host/backup
security remain residual risks. Do not promote `main` or call this generally
released until the separate gate and owner decision are recorded.

## Review order and rollback

Portal PR first, then Core PR against the exact Portal head; record both SHAs
in both PR descriptions. Re-run pairing checks after any review fix. Final
independent affirmative/skeptical reviews are advice, not owner approval.
No merge or deployment is part of this train. Source rollback is a paired
revert; no database restore is required for these changes. If a test install
was executed elsewhere, preserve its data and stop only its generated jobs
before explicitly selecting/redeploying the prior source pair.
