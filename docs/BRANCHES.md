# Branch and deployment model

This repository uses a small production/integration split:

- `main` is the stable and recoverable release source, reserved for reviewed
  pull requests.
- `dev` is the only branch for ongoing work, commits and local deployment.
- Short-lived `feature/<name>` or `fix/<name>` branches are optional for
  risky or easily isolated work and merge back into `dev`.

All changes must be committed on `dev`. Promotion to `main` is a pull request
reviewed and explicitly approved by `@TrygveAasheim`; normal work must not push
directly to `main`. `.github/CODEOWNERS` requests that review for every file.

GitHub branch protection is enabled on `main`: direct pushes, force pushes and
deletions are blocked; administrators are covered; conversations must be
resolved; and a fresh pull-request review from a code owner is required.
The strict `Portal checks` and `CodeQL` workflows must also pass before
merging.

The dev verification and deployment workflow is:

1. work and commit on `dev`;
2. run unit tests, build, lint, privacy scan and relevant acceptance checks;
3. push the verified commit to `dev`;
4. deploy from `dev` and verify the local service;
5. open a pull request from `dev` to `main` when release promotion is wanted.

The deployment script refuses to run from any branch other than `dev`.
Private runtime state is never merged into either branch.
