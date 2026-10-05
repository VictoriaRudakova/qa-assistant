# ADR 0004: Secrets from environment; synthetic test data; project-scoped Jira

- Status: Accepted
- Date: 2026-10-05

## Decision

- All credentials come from environment variables, optionally via a git-ignored `.env`.
  Settings hold tokens as `SecretStr`, and logs redact known secrets and `Authorization`
  values.
- The committed `.env.example` contains variable names only. Blank values mean "unset".
- Jira access uses a TEST instance and a read-only account. Every read is restricted to
  `JIRA_PROJECT_KEY` by a deterministic wrapper (`ProjectScopedJiraClient`).
- Test fixtures are synthetic (project `DEMO`, `example.com`). A test scans all fixtures for
  non-example domains, unexpected project keys and token-like strings.
- Secret scanning runs as a pre-commit hook and in CI (gitleaks).
- Claude Code project settings deny reading `.env`.

## Consequences

Real company data and credentials stay out of the repository and out of test logs. Moving
to a production Jira later is a configuration change plus a review of the project scope.
