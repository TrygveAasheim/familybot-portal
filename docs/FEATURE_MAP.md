# FamilyBot prototype feature map

The integrated portal exposes the first five surfaces and a `/lab` route that
keeps later experiments explicit. Proposed order:

1. Reliability and recovery in the FamilyBot lab clone.
2. Read-only status contract and portal evaluation with fixtures.
3. Canonical calendar plus optional ICS export.
4. Corrections, uncertainty states and source provenance.
5. Chore suggestions with adult approval.
6. Notification policy, backups/restore drills and Spond fallback.
7. Optional quality-of-life features such as meals only after their source and
   family value are clear.

Each backend experiment gets its own branch in `familybot-lab`; each UI
experiment gets its own branch in `familybot-portal`. The integration branch is
a review surface, not a deployment signal.
