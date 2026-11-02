# Configuration source

There is intentionally no portal-specific family template. Use the single
canonical template in the sibling `familybot-core` repository:

`../familybot-core/config/family.example.json`

See `../familybot-core/CONFIGURATION.md`. Both applications read
`$HOME/.openclaw/workspace/config/family.local.json` unless an explicit
`FAMILYBOT_FAMILY_CONFIG` override is set.

Optional Portal experiments are also declared in that canonical file. The
read-only Norwegian HelloFresh menu is disabled by default and can be enabled
with:

```json
"portal": {
  "features": {
    "hellofresh": true
  }
}
```

This flag exposes public menu data only; it does not enable HelloFresh account
login, credentials, meal selection, ordering, delivery or subscription writes.
