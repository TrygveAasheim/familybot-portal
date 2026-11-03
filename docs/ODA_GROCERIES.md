# Oda grocery integration

## Change record

- Change type: feature and improvement.
- Problem or intent: keep the focused grocery workflow, then add a bounded
  dinner conversation that can use Oda recipe preferences and add a selected
  recipe's ingredients to the cart.
- Evidence: the chat was not used; Oda publishes a remote OAuth MCP server with
  product, recommendation and cart tools while keeping checkout/payment in the
  shop.
- Scope and owner: Portal UI, curated local API, OAuth credential storage and a
  narrow external Oda adapter. FamilyBot Core and SQLite are unchanged.
- Acceptance criteria: AC-18 in
  `ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md`.
- Tests: OAuth/PKCE and MCP protocol unit tests, dinner planner validation and
  fallback tests, recipe/cart API authorization tests, rendered-source
  assertions, full Portal suite and live acceptance check.
- Security/privacy: every valid trusted-LAN Portal session may use Oda; OAuth
  tokens remain server-side in an owner-only file; no generic MCP proxy, order
  history endpoint, saved address endpoint, generic model chat, checkout or
  payment operation is exposed. The dinner planner receives only the bounded
  request, short conversation history and a small list of recipe titles; its
  isolated agent has no tools.
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
- asking for dinner suggestions in Norwegian, informed by liked and previously
  purchased Oda recipe titles when available;
- showing each recipe's public Oda hero image directly in the suggestion card;
- opening bounded public recipe details inside the Portal with an explicit
  return button, without popup or browser-back dependencies;
- adding all available ingredients for the chosen number of portions after an
  explicit button press;
- reading the current cart;
- adding one product or removing one unit;
- clearing the cart after an explicit browser confirmation;
- opening Oda's cart link for final review and payment.

The adapter has no route that accepts an arbitrary MCP tool name. Its source
allowlist maps only to `product_search`, `likely_to_buy`, `get_cart`,
`recipe_search`, `get_liked_recipes`, `get_purchased_recipes`,
`manipulate_cart` and `clear_cart`.

## Dinner assistant boundary

Oda exposes recipe tools, not a general chat model. The Portal therefore uses
an isolated `familybot-oda-dinner` OpenClaw agent with an OpenAI model and no
tools or skills. It can only propose one to three bounded recipe search phrases
and a short Norwegian reply. The model receives:

- the current dinner request and number of portions;
- at most six bounded dinner-chat messages; and
- at most sixteen titles from liked or previously purchased Oda recipes.

It does not receive names, schedules, Ukeplan, family SQLite data, OAuth tokens,
product history, addresses or cart contents. Search results come from Oda after
the model call. If the planner is unavailable or malformed, the Portal falls
back to a direct Oda recipe search, so recipe discovery does not depend on the
model.

The model cannot call MCP or mutate anything. A recipe's ingredients are added
only by the separate `POST /api/oda/recipes/{id}/cart` route after the user
presses the recipe button. The route accepts only a positive Oda recipe ID and
1–12 portions. Checkout remains at Oda.

The MCP recipe schema does not include images, ingredients or instructions.
After Oda returns a recipe URL,
the server may read that public `https://oda.com/{locale}/recipes/{id}-.../`
page and extract its `og:image` plus bounded schema.org `Recipe` presentation
fields. Both the final page and image are checked against strict Oda hosts and
recipe paths, HTML reads are size/time bounded, text and list lengths are
capped, lookups run in a small worker pool and results are cached. Only Oda's current
`https://images.oda.com/recipes/...` or legacy Norwegian
`https://images.oda.com/oppskrifter/...` paths are returned to the browser. If the image
cannot be verified, the card shows a local placeholder and recipe search still
succeeds. A selected recipe is rendered in a Portal-owned dialog with
**Tilbake til middagsforslag**, because Oda disallows framing and kiosk mode
does not expose dependable browser-back controls.

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
