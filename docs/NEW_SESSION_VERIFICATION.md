# New-session portal verification

This drill verifies that a fresh session can safely change the portal using only
tracked files.

## Automated check

```bash
npm run docs:check
```

The validator checks required handoff files, local Markdown links, fenced code
blocks and package entry points.

## Cold-start questions

A new session starts at `AGENTS.md` and must identify:

| Question | Answer location |
| --- | --- |
| What does this repo own? | `docs/DEVELOPMENT_GUIDE.md` |
| Which fields/actions may reach the browser? | `docs/DATA_BOUNDARY.md` |
| What makes an iPad release acceptable? | `docs/ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md` |
| Which features exist versus remain planned? | `docs/FEATURE_MAP.md` |
| How are full 30-point blocks and surprise redemptions counted? | `docs/WEEKLY_ACHIEVEMENTS.md` |
| Where is family configuration defined? | `config/README.md` and sibling core |
| How is production deployed? | `README.md`, `scripts/deploy-local.sh` |

## Scenario drill

The documentation passes if the session makes these choices:

1. A new UI card gets a curated API contract and acceptance evidence; it does
   not query raw SQLite from browser code.
2. A new mutation receives authorization, validation, audit and idempotency
   tests.
3. Smart Home uses a server-side allowlist and separate page; it cannot expose a
   generic Home Assistant service endpoint.
4. An email-routing defect is handed to `familybot-core`; it is not patched in
   presentation code.
5. A documentation-only release is committed but does not restart the runtime.

## Clean tracked-files check

```bash
temporary_directory="$(mktemp -d)"
git archive HEAD | tar -x -C "$temporary_directory"
python3 "$temporary_directory/scripts/validate_docs.py" \
  --root "$temporary_directory"
```

The archive must not contain the parent PIN, audit log, database, generated
runtime or populated family configuration.
