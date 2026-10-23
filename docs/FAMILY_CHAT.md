# Family chat

## Change record

- Change type: feature.
- Intent: add an all-user, read-only `Spør FamilyBot` tab grounded in the
  Portal's curated household data, while retaining general-knowledge answers.
- Evidence: the dashboard has no conversational surface; users must navigate
  individual cards or use Telegram for follow-up questions.
- Scope: Portal UI, local API and an isolated OpenClaw agent. Core ingestion,
  SQLite schemas, delivery and Telegram are unchanged.
- Acceptance: every dashboard user can ask in Norwegian or English; Sol runs
  at medium reasoning; current curated facts and full current ukeplans are
  available; general questions and fresh public-information questions work;
  chat cannot mutate state or use messaging, filesystem, shell, arbitrary URL
  fetch, browser, memory, automation or plugin tools.
- Tests: request bounds, context allowlist, prompt/data separation, private
  prompt file, isolated agent session, generic errors, local-session
  authorization, rate limiting, UI/build assertions and AC-18.
- Privacy: the UI states that each question, visible browser history and the
  curated context are sent to OpenAI. No credentials, PIN, raw email, sender
  address, Telegram ID, raw Spond payload or storage ID is included. Prompts
  and answers are not written to Portal logs or SQLite.
- State/deployment: no migration. Deployment creates the private
  `familybot-chat` OpenClaw agent and applies its minimal policy with hosted
  public web search before restarting Portal. Browser chat history is held only
  in `sessionStorage`.
- Rollback: redeploy the previous Portal commit. The isolated agent may remain
  inert; removing it is optional and does not affect family state.

## Runtime design

`POST /api/chat` requires the same allowed Origin and rotating local session
token as dashboard reads. It deliberately does not require the parent PIN.
Input is limited to 2,000 characters, ten prior messages and 12,000 history
characters. One inference runs at a time, with eight accepted requests per
client per five minutes and a bounded timeout.

The server constructs an explicit context containing current children/chores,
recent visible completion history, rewards and full-block progress, calendar
and Spond events, recurring activities, active family Kanban, current full
week plans, school dates, weather, transport, health summary and vacation mode.
Database identifiers are removed. Unlinked email summaries, raw source data,
process details and configuration do not enter the prompt.

The default runtime is `openai/gpt-5.6-sol` with `medium` thinking. A fresh
isolated model session is used for every request; the visible conversation is
provided explicitly by the browser. The dedicated agent has the `minimal` tool
profile, an empty skill list, elevated mode disabled and an explicit allowance
for `web_search`. Runtime, filesystem, arbitrary URL fetch, X search, memory,
UI, automation, messaging, nodes, agents, media and plugin tools remain denied.
Hosted search uses the existing OpenAI/ChatGPT sign-in; no additional search
credential is stored by Portal.

## Temporary harness

The v1 harness lives only in `local_api/familybot_chat.py` so it can be replaced
without changing UI, authorization or context curation. It treats every value
inside `FAMILYBOT_DATA` as untrusted data rather than instructions, requires
family claims to be grounded in that data, distinguishes general knowledge and
external sources, requires search for current public facts, prohibits private
family facts in search queries and refuses action requests.

This is a useful safety baseline, not a semantic guarantee. A later reviewed
harness should retain the immutable boundaries: curated input, no tools that
can act or retrieve new private data, explicit uncertainty and representative
Norwegian evaluation questions.
