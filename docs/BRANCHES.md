# Branch and deployment model

This repository uses a small production/integration split:

- `main` is the stable, deployable and recoverable production source.
- `dev` is the normal integration branch for ongoing FamilyBot work.
- Short-lived `feature/<name>` or `fix/<name>` branches are optional for
  risky or easily isolated work and merge back into `dev`.

There is no mandatory pull-request ceremony while the repository has only its
current owner and Codex collaborator. Promotion is still deliberate:

1. work and commit on `dev`;
2. run unit tests, build, lint, privacy scan and relevant acceptance checks;
3. fast-forward `main` to the verified `dev` commit;
4. push `main`;
5. deploy from `main` and verify the local service;
6. return the working checkout to `dev`.

Production must not be deployed directly from an unverified feature branch.
Private runtime state is never merged into either branch.
