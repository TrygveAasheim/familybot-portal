# Security policy

Familieportalen is a self-hosted household dashboard. Do not disclose family
data, credentials, tokens, API responses or private configuration in a public
issue or pull request.

Please report suspected vulnerabilities privately to the repository owner via
GitHub's private vulnerability reporting flow when available. Include the
affected repository, commit or version, reproduction steps and impact, but
remove household data and all secret values. If private reporting is not
available, contact the owner through the GitHub profile before publishing
details.

Security-sensitive changes must be reviewed and approved by `@TrygveAasheim`
before they are promoted to `main`.

The `dev` and pull-request checks audit production and development dependencies
at the low threshold. Production findings always fail. A development-only
finding may pass only when its exact GHSA identifier is documented in
`scripts/audit-dependencies.mjs`; unknown or additional advisories still fail.
The current `minimatch` exception covers lint tooling that cannot yet consume
the patched major version and must be removed once that toolchain is compatible.
