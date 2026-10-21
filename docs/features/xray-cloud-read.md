# Feature: read an Xray Cloud Test

`get_xray_test(issue_key, step_offset=0)` reads one existing Xray Cloud Test by its Jira
issue key, supplied at runtime. It is read-only and is the base for the publishing milestone
(Generated Tests -> Validation -> Preview -> Approval -> Publish -> Requirement Linking),
which will use it to find existing tests and avoid duplicates.

Nothing in the client depends on a project, issue, story or business domain: the project
scope and endpoints are configuration, and the parsing is driven by Xray's schema only.

## Configuration

| Variable | Required | Meaning |
|---|---|---|
| `XRAY_CLIENT_ID`, `XRAY_CLIENT_SECRET` | yes | Xray Cloud API key (Xray settings, API Keys). Secrets: redacted from logs, never returned. |
| `JIRA_PROJECT_KEY` | yes | The existing Jira scope; Xray has no scope setting of its own. |
| Other `JIRA_*` (base URL, credentials) | yes | Tenant identity check (below). |
| `XRAY_CLOUD_BASE_URL` | no | Default `https://xray.cloud.getxray.app`; data-residency tenants set their region (`us`, `eu`, `au` `.xray.cloud.getxray.app`). https only. |
| `XRAY_TIMEOUT_SECONDS` | no | Default 30. |
| `JIRA_BASE_URL` | no | When set, the result has a browse `url`. |

Without the required variables the tool returns `[not_configured]` naming them.
`JIRA_DEPLOYMENT=data_center` is refused: Xray Cloud only runs on Jira Cloud, and Xray
Server/Data Center (a different REST API) is not supported.

## Tenant identity (fail closed)

An Xray API key belongs to one Jira Cloud site, and nothing in Xray's API names that site.
So every read is checked against the configured Jira (`JIRA_*`), and Jira is required:

1. The key must be in `JIRA_PROJECT_KEY`. Nothing is requested otherwise.
2. Jira (`GET /rest/api/{2,3}/issue/<key>?fields=project`, project-scoped) must know the
   issue and return its numeric issue id and project id. An issue that has moved, so that
   Jira answers with another key or project, counts as outside the scope.
3. Xray's `issueId` and `projectId` for the Test must equal Jira's.

**Limit:** this cross-check is useful, but it does not by itself guarantee that the tenant
is the same. Numeric ids are unique within one Jira site, not across sites. Another site
could, by coincidence, have an issue with the same key, issue id and project id. That is
unlikely, but nothing in the check rules it out. The check catches the realistic mistakes
(an API key of another site, a key that resolves to a different issue). It does not prove
that the API key belongs to `JIRA_BASE_URL`, because Xray's API has no call that names its
Jira site. Identity ultimately rests on configuring the Xray API key for the intended site.

A mismatch is `[xray_error] ... the Xray API key may belong to another Jira site. No Test
data was returned.` No requirements are fetched after it. If Jira is not configured, or is
a fixture backend without ids, the tool returns `[not_configured]` and reads nothing.

## API contract (Xray Cloud API v2, checked against the official docs on 2026-10-21)

- `POST /api/v2/authenticate` with `{"client_id", "client_secret"}` returns the bearer token
  as a JSON string. The token is kept in memory and renewed once when a query gets HTTP 401.
- `POST /api/v2/graphql` with `getTests(jql, limit: 1)`. The fields used are `issueId`,
  `projectId`, `testType {name kind}`, `steps {id action data result callTestIssueId}`,
  `gherkin`, `unstructured`, `folder {path}`, `lastModified` and `jira(fields: [...])`.
- Requirements come from `Test.coverableIssues(limit, start)`, which has at most 100 items
  per page. Further pages are fetched with `getTests(issueIds: [...])`.
- Limits: every connection needs a `limit` of 100 or less, a call may return at most 10,000
  items and use at most 25 resolvers, and rate limits are 300 requests per 5 minutes
  (Standard) or 1,000 (Enterprise). A tool call makes one query, plus one
  `authenticate` when there is no valid token yet, plus one query per further 100
  requirements (at most 2 queries for requirements).

## Result and bounds

The result is an `XrayTest` (`src/qa_assistant/domain/xray.py`): key, ids, summary, status,
labels, test type, folder path, last modified, the Gherkin or unstructured `definition`,
`steps` (`action`, `data`, `expected_result`, called test), and `requirements`.

- **Steps are paged.** Each call returns at most 50 steps and 40,000 characters of step
  text. Follow `next_step_offset`; `steps_total` gives the full count. A step field longer
  than 4,000 characters is cut and the step is marked `truncated`.
- **Requirements** are capped at 200 (`requirements_total`, `requirements_truncated`).
  A covered issue outside `JIRA_PROJECT_KEY` is returned with its key only.
- **Definitions** are capped at 20,000 characters.
- **Untrusted text.** Test text is untrusted data. Instruction-like text is flagged in
  `untrusted_instructions`, using the same tripwire as Jira stories.

## Validation and errors

| Case | Result |
|---|---|
| Key not matching `^[A-Z][A-Z0-9_]+-[1-9]\d*$` | rejected by the tool schema; no request |
| Key outside `JIRA_PROJECT_KEY` | `[not_found]`; no request |
| Issue unknown to the configured Jira, or moved out of the project | `[not_found]`; Xray not called |
| No such Test (or not visible to the API key) | `[not_found]` |
| Xray's issue id or project id differs from Jira's | `[xray_error]`, no Test data |
| API key rejected, token rejected twice, 403, 429, redirect, 5xx, timeout, network | `[xray_error]`, with no credentials, token or headers in the message |
| GraphQL `errors`, non-JSON, or a response not matching the schema | `[xray_error]` (GraphQL message truncated) |
| Returned issue key differs from the requested one | `[xray_error]` |

## Safety

- Read-only. The transport has no generic POST: it sends `authenticate` and GraphQL
  documents that start with `query` (it raises on anything else, so a mutation cannot be
  sent). The Jira identity read is one GET through the existing read-only client.
- The MCP tool is not in the auto-allow list in `.claude/settings.json`, so each call is
  confirmed. The guard hook blocks direct Xray API calls from the shell or WebFetch.
- Tests use synthetic fixtures (`tests/fixtures/xray/DEMO-201.get_tests.json`) and
  `httpx.MockTransport`; nothing goes to the network.

## Live smoke test (opt-in, never automatic)

```bash
XRAY_LIVE_TEST_ISSUE=<KEY> uv run pytest -m live tests/live/test_xray_live.py -s
```

The test reads the issue key at runtime and skips without configuration. Its transport
allows only `authenticate` and GraphQL `query` requests. Its assertions compare keys, counts
and booleans, so a failure never prints credentials or Test content.
