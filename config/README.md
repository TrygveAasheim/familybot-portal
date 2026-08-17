# Configuration source

There is intentionally no portal-specific family template. Use the single
canonical template in the sibling `familybot-core` repository:

`../familybot-core/config/family.example.json`

See `../familybot-core/CONFIGURATION.md`. Both applications read
`$HOME/.openclaw/workspace/config/family.local.json` unless an explicit
`FAMILYBOT_FAMILY_CONFIG` override is set.
