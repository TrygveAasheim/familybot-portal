# Clean-host redeployment

This checklist separates reproducible source from private household state. Git
restores the application; it does not restore the family database or secrets.

## Protected inputs required

Keep these outside Git in an encrypted or otherwise access-controlled backup:

- `$HOME/.openclaw/workspace/config/family.local.json`;
- `$HOME/.openclaw/workspace/db/family.db`;
- OpenClaw and Telegram credentials;
- mail-client configuration and credentials;
- Spond authentication state, if used;
- `runtime/parent-pin.txt`;
- any attachments or operational memory the family wants to retain.

The portal cannot create the complete FamilyBot database from nothing.
`dashboard_migration.py` only adds the portal chores/rewards tables to an
existing core database.

## Ordered restore

1. Install macOS Command Line Tools, Node.js/npm, Python 3.9+ and OpenClaw.
2. Clone `familybot-core` and `familybot-portal`.
3. Restore or initialize `$HOME/.openclaw/workspace`.
4. Restore `db/family.db` and verify it with
   `sqlite3 "$HOME/.openclaw/workspace/db/family.db" "PRAGMA integrity_check;"`.
5. Restore the protected local config, or create it from the repository template:

   ```bash
   install -d -m 700 "$HOME/.openclaw/workspace/config"
   install -m 600 config/family.example.json \
     "$HOME/.openclaw/workspace/config/family.local.json"
   ${EDITOR:-nano} "$HOME/.openclaw/workspace/config/family.local.json"
   chmod 600 "$HOME/.openclaw/workspace/config/family.local.json"
   ```

6. Replace all applicable uppercase placeholders. Remove unused optional
   second-location entries. Never enter API tokens in this JSON file.
7. Restore the parent PIN to `runtime/parent-pin.txt` with mode `0600`.
8. Restore OpenClaw/Telegram, mail and Spond credentials in their own local
   stores and verify each integration independently.
9. From the portal repository, run:

   ```bash
   npm ci
   npm run lint
   npm test
   bash scripts/deploy-local.sh
   python3 tests/acceptance.py
   ```

10. Verify `http://familie.local:3000/` from the Mac and an iPad on the home
    LAN. Confirm child completion, parent approval, weather and Entur countdown.

## Path overrides

- `FAMILYBOT_WORKSPACE`: alternate OpenClaw workspace root.
- `FAMILYBOT_FAMILY_CONFIG`: alternate populated family JSON path.
- `FAMILYBOT_PORTAL_RUNTIME`: alternate deployed portal runtime.

Apply the same environment to interactive tests and LaunchAgents. launchd does
not inherit shell startup files, so non-default overrides must be placed
explicitly in the relevant plist.
