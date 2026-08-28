# 30-point block achievement specification

This is the portal contract for counting completed 30-point blocks and allowing
a parent to attach redeemable surprises to that progress. It is separate from
FamilyBot Core's source and delivery ledgers. The legacy table and API field
names still contain `week` for compatibility, but the progress unit is now a
continuous block of points rather than a calendar week.

## Rules

- The target is 30 points per block.
- Completions with `status IN ('pending', 'awarded')` contribute their recorded
  points. Pending points are visible immediately while awaiting parent review;
  a rejection changes the completion to `rejected` and sets its points to zero,
  removing them from progress.
- Pending-plus-awarded points are summed from the start of the active cycle.
  Every 30 points fills one block; any remainder immediately starts the next
  progress bar. Rejected completions contribute zero.
- The current remainder and number of full blocks are shown to the child. A
  new block starts immediately when the previous one reaches 30 points; there
  is no Monday reset and no ISO-week grouping.
- Parents can configure multiple active levels, each with a positive threshold
  in full weeks, a title and an emoji. A level is ready when the count reaches
  its threshold and it has not already been redeemed in the active cycle.
- Redeeming a surprise ends the current cycle and starts a new one at zero. The
  prior cycle and redemption remain stored for history; configured levels stay
  available for the new cycle.

## Parent API

All routes require an authenticated parent session and use the portal's normal
backup, audit and validation rules:

- `POST /api/children/{child_id}/weekly-achievement/surprises` creates or
  updates a level.
- `DELETE /api/children/{child_id}/weekly-achievement/surprises/{threshold}`
  removes a level that has not been redeemed in the active cycle.
- `POST /api/children/{child_id}/weekly-achievement/reset` records a selected
  surprise and starts a fresh achievement cycle. An idempotency key makes a
  repeated request safe.

The child-facing dashboard exposes progress, ready levels, the next level and
redemption history as curated fields. It never exposes raw SQLite rows,
credentials or FamilyBot source payloads.

## Storage

The portal migration owns these tables:

- `weekly_achievement_cycles` — active and historical cycle boundaries and
  target points;
- `weekly_surprise_levels` — configured thresholds and presentation text;
- `weekly_achievement_redemptions` — redeemed levels and cycle history;
- `weekly_achievement_reset_operations` — idempotency records for resets.

The implementation derives continuous totals from portal completion rows whose
status is `pending` or `awarded`, starting at the active cycle boundary. It
does not write to FamilyBot Core tables.

## January summary

During January, the family dashboard shows a one-time-per-session summary of
the previous calendar year's retained child-completion counts. It includes
approved and pending completions, excludes rejected completions, and continues
to count completions after a chore is archived.
