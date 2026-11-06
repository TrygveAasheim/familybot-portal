# Configuration source

There is intentionally no portal-specific family template. Use the single
canonical template in the sibling `familybot-core` repository:

`../familybot-core/config/family.example.json`

See `../familybot-core/CONFIGURATION.md`. New installations use
`$HOME/.familybot/config/family.local.json`; both applications receive its exact
path through `FAMILYBOT_FAMILY_CONFIG`. Existing deployments may retain an older
explicit workspace path.

Optional Portal experiments are also declared in that canonical file. The
Norwegian HelloFresh menu and account test are disabled by default and can be
enabled in stages (account access requires the public-menu flag) with:

```json
"portal": {
  "features": {
    "hellofresh": true,
    "hellofresh_account": true
  }
}
```

The first flag exposes public menu data. The second replaces the visible Oda
tab with in-Portal HelloFresh email/password login. On first use the password
travels once over the trusted home LAN to the local API, which forwards it to
the fixed HelloFresh Norway endpoint using a Chrome-fingerprinted, verified
HTTPS transport. The password remains transient request data and is never
stored, logged, returned or placed in model context. There is no email-link
fallback: HelloFresh maps that flow to password reset for this market/account.
Only refresh credentials are written beneath the configured private workspace,
normally `$HOME/.familybot/credentials/hellofresh-no.json`, with mode `0600`. Account
access is limited to viewing future boxes, replacing/adding/removing selected
meals and pausing or resuming one identified week after explicit confirmation.
Subscription-plan, servings, address, payment, checkout and ordering controls
remain unavailable. Both flags default to `false`.

Oda is independently opt-in: set `portal.features.oda` to `true` for recipe,
product and cart operations. `portal.features.oda_ai` defaults to false and
requires Oda, an isolated OpenClaw dinner agent and consent to external model
processing. Direct search/cart needs no AI. All omitted grocery flags are false,
including in legacy files: add explicit flags to retain those capabilities on
upgrade. Workspace precedence and explicit legacy overrides are documented in
Core's CONFIGURATION.md; no private legacy state is discovered automatically.
