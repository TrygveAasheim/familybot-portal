# Branch and deployment model

This repository uses a small release/integration split:

- `main` is the public source and fork baseline, including the coordinated
  installation candidate. Publication does not certify unperformed hardware or
  provider checks; see the installation readiness assessment.
- `dev` is the integration branch and default local deployment track.
- Short-lived `feature/<name>` or `fix/<name>` branches are optional for
  risky or easily isolated work and merge back into `dev`.

Normal work and deployment happen on `dev`. Promotion of a verified release to
`main` is an owner-controlled release operation. GitHub branch protection is
intentionally not enabled: external users are expected to fork the repository
for customization rather than contribute changes through the upstream release
branch. CI and CodeQL still run on pushes and pull requests where applicable.

The dev verification and deployment workflow is:

1. work on a dedicated branch and open a reviewed PR into `dev`;
2. run unit tests, build, lint, privacy scan and relevant acceptance checks;
3. push the feature branch and merge to `dev` only after separate approval;
4. only when separately authorized, deploy from `dev` and verify the local service;
5. promote verified `dev` through an owner-reviewed and approved PR into
   `main` when a new public fork baseline is wanted, documenting outstanding
   hardware/provider gates. Source publication does not require deploying the
   owner's existing household.

Deployment is a separately authorized action, not an automatic consequence of
a review, commit or PR. PR-only work stops with reviewed open PRs and leaves the
existing installation unchanged.

The deployment script defaults to `dev`. Fork maintainers may set
`FAMILYBOT_DEPLOY_BRANCH` to their own reviewed local release branch. This
changes only the branch-name guard; every preflight, test, backup, migration and
acceptance requirement remains in force. Private runtime state is never merged
into any branch.
