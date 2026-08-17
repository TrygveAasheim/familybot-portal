# Prototype branches

- `main`: untouched Sites scaffold.
- `prototype/operations-dashboard`: visual shell, reliability dashboard and
  explicit read-only boundary.
- `prototype/week-calendar`: week and calendar exploration, based on operations.
- `prototype/chores-dashboard`: household jobs exploration, based on operations.
- `prototype/inbox-audit`: email/source audit exploration, based on operations.
- `prototype/integration`: the selected ideas consolidated into one functional,
  local-only household screen with a curated SQLite bridge.

No prototype branch is deployed into `$HOME/.openclaw/workspace`.
The integration branch reads that workspace only while its local API is running;
its only permitted writes are guarded chore mutations.
