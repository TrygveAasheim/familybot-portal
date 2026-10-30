# Oda grocery integration

## Change record

- Change type: feature and removal.
- Problem or intent: remove the unused general AI chat and replace it with a
  focused grocery workflow backed by Oda's hosted MCP server.
- Evidence: the chat was not used; Oda publishes a remote OAuth MCP server with
  product, recommendation and cart tools while keeping checkout/payment in the
  shop.
- Scope and owner: Portal UI, curated local API, OAuth credential storage and a
  narrow external Oda adapter. FamilyBot Core and SQLite are unchanged.
- Acceptance criteria: AC-18 in
  `ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md`.
- Tests: OAuth/PKCE and MCP protocol unit tests, API authorization tests,
  rendered-source assertions, full Portal suite and live acceptance check.
- Security/privacy: every valid trusted-LAN Portal session may use Oda; OAuth
  tokens remain server-side in an owner-only file; no generic MCP proxy, order
  history, saved address endpoint, AI model, checkout or payment operation is
  exposed.
- State and deployment: no SQLite migration. The first connection dynamically
  registers the local Portal client and navigates the current browser window to
  Oda's login/consent page, which is compatible with kiosk popup restrictions.
- Rollback: revert the source commit, redeploy Portal and revoke FamilyBot
  access under Oda's Privacy & security settings. The Oda cart itself remains
  in the Oda account.
- Documentation: README, feature map, development guide, data boundary and
  acceptance contract updated together.

## Supported flow

The top-level `Oda` tab is available to all users who already have a valid
local dashboard session. It supports:

- connecting or disconnecting the household Oda account through OAuth;
- searching products;
- loading Oda's `likely_to_buy` suggestions;
- reading the current cart;
- adding one product or removing one unit;
- clearing the cart after an explicit browser confirmation;
- opening Oda's cart link for final review and payment.

The adapter has no route that accepts an arbitrary MCP tool name. Its source
allowlist maps only to `product_search`, `likely_to_buy`, `get_cart`,
`manipulate_cart` and `clear_cart`.

## Account connection

1. Deploy Portal and open `http://familie.local:3000/?oda=1`.
2. Choose **Logg inn hos Oda**. Oda opens in the current browser window, so no
   popup permission is needed.
3. Sign in to Oda and approve the connection.
4. The OAuth callback returns to the Oda tab automatically and confirms the
   connection. If automatic navigation is unavailable, the callback page also
   provides an explicit **Tilbake til Familieportalen** link.

The OAuth callback defaults to
`http://familie.local:8788/api/oda/oauth/callback`. A customized deployment may
set `FAMILYBOT_ODA_CALLBACK_URL`, but that exact URL must be reachable from the
browser used for Oda consent.

Credentials are stored outside both repositories at
`$HOME/.openclaw/credentials/oda-mcp.json` with file mode `0600` and directory
mode `0700`. They must never be copied into Git, browser responses, support
logs or screenshots. Disconnecting revokes the grant before removing local
tokens. Oda also lets the account owner revoke MCP access under Privacy &
security.

## Failure and purchasing boundary

Expired access tokens refresh server-side. If refresh fails, the UI asks for a
new connection without affecting the rest of Familieportalen. Provider errors
are reduced to local Norwegian messages; Oda response bodies and tokens are not
logged.

MCP can prepare the cart but cannot place or pay for an order. The final button
opens Oda, where the user reviews products, delivery details and total before
paying. Do not add an automated checkout workaround.
