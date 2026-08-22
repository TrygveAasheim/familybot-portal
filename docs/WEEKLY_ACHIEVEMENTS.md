# Weekly achievement specification

This is the portal contract for counting completed chore weeks and allowing a
parent to attach redeemable surprises to that progress. It is separate from
FamilyBot Core's source and delivery ledgers.

## Rules

- The target is 30 approved points in one ISO calendar week.
- Only completions with `status = 'awarded'` contribute points.
- A week is full when its approved points reach the target. A full week counts
  once per active achievement cycle, even if later approvals change its point
  total.
- The current week's approved points and the number of full weeks are shown to
  the child. The count continues across calendar weeks until a parent redeems a
  surprise.
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

The implementation derives ISO-week totals from approved portal completion
rows and does not write to FamilyBot Core tables.
