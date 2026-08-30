# Branch and deployment model

This repository uses a small release/integration split:

- `main` is the stable public release and fork baseline.
- `dev` is the only branch for ongoing work, commits and local deployment.
- Short-lived `feature/<name>` or `fix/<name>` branches are optional for
  risky or easily isolated work and merge back into `dev`.

Normal work and deployment happen on `dev`. Promotion of a verified release to
`main` is an owner-controlled release operation. GitHub branch protection is
intentionally not enabled: external users are expected to fork the repository
for customization rather than contribute changes through the upstream release
branch. CI and CodeQL still run on pushes and pull requests where applicable.

The dev verification and deployment workflow is:

1. work and commit on `dev`;
2. run unit tests, build, lint, privacy scan and relevant acceptance checks;
3. push the verified commit to `dev`;
4. deploy from `dev` and verify the local service;
5. promote the verified `dev` state to `main` when a new public fork baseline is
   wanted.

The deployment script refuses to run from any branch other than `dev`.
Private runtime state is never merged into either branch.
