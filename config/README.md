# Configuration source

There is intentionally no portal-specific family template. Use the single
canonical template in the sibling `familybot-core` repository:

`../familybot-core/config/family.example.json`

See `../familybot-core/CONFIGURATION.md`. Both applications read
`$HOME/.openclaw/workspace/config/family.local.json` unless an explicit
`FAMILYBOT_FAMILY_CONFIG` override is set.

Optional Portal experiments are also declared in that canonical file. The
Norwegian HelloFresh menu and account test are disabled by default and can be
enabled independently with:

```json
"portal": {
  "features": {
    "hellofresh": true,
    "hellofresh_account": true
  }
}
```

The first flag exposes public menu data. The second replaces the visible Oda
tab with in-Portal HelloFresh email/password login. On first use the browser
sends the password directly to HelloFresh over HTTPS and immediately hands the
allowlisted token result to the Portal; the password is never sent to the local
API or stored. Only refresh credentials are written to
`$HOME/.openclaw/credentials/hellofresh-no.json` with mode `0600`. Account
access is read-only: meal selection, ordering, delivery and subscription writes
remain disabled.
