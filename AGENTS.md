# Familieportalen agent contract

This is the mandatory entry point for coding agents and fresh development
sessions working in `familybot-portal`. It applies to the entire repository.

## Read before changing anything

Read these files in order:

1. `README.md`
2. `docs/DEVELOPMENT_GUIDE.md`
3. `docs/DATA_BOUNDARY.md`
4. `docs/ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md`
5. `docs/FEATURE_MAP.md`

When the sibling core repository is available, also read
`../familybot-core/AGENTS.md`, `../familybot-core/docs/REPOSITORY_GUIDE.md` and
`../familybot-core/specs/RELIABILITY.md`. Smart Home work additionally requires
`../familybot-core/specs/SMART_HOME.md`.

## Non-negotiable boundaries

- The portal is a family appliance, not an OpenClaw or SQLite administration
  console. Browser contracts expose curated fields only.
- Raw email, raw Spond JSON, Telegram identifiers, credentials, attachments and
  arbitrary filesystem paths never enter browser responses.
- The portal cannot mark ingestion complete, mutate the delivery outbox, trigger
  scheduled jobs or send Telegram messages.
- Children need large, tap-first controls and no typing for normal use. Parent
  mutations require a parent session.
- User-visible unavailable/stale states are honest. Do not convert a missing
  source into a healthy or empty-looking result.
- Smart Home is an add-on behind a narrow provider adapter. The browser must not
  proxy arbitrary Home Assistant services.

## Required verification

```bash
npm run docs:check
npm run lint
npm test
python3 tests/acceptance.py
git diff --check
```

Run `npm run preflight` before deployment with the real ignored config, PIN and
database available. All 17 current critical acceptance criteria must pass.
Extend the acceptance contract before shipping a new user-visible capability.

Normal work is committed and deployed from `dev` only. `main` is the stable
release branch and must only receive reviewed pull requests; do not commit,
push or deploy directly from `main`. Runtime files, PINs, audit logs and
databases never enter Git.

## Deployment invariant

Every deployment must force a client-side web refresh for all open dashboards.
The managed service restart must rotate the API session generation, and the
browser must compare that generation during its normal poll and call
`window.location.reload()` when it changes. Do not remove this behavior or
deploy a web-only change that bypasses it.
