# MCP tools

Server name: `qa-assistant` (stdio). In Claude Code the tools appear as `mcp__qa-assistant__<tool>`.

**Source of truth:**
- Exact input and output schemas: `tests/mcp/snapshots/tool_schemas.json` (pinned by tests).
- Behaviour: `src/qa_assistant/mcp/server.py`, which delegates to `src/qa_assistant/services/`.

This page doesn't copy those schemas.

## Tools by kind

| Kind | Tools |
|---|---|
| Jira reads (project-scoped) | `jira_get_story`, `jira_search_stories` |
| Local reads | `get_run`, `list_runs`, `validate_test_cases` |
| Local writes (`output/runs/` only) | `submit_story_analysis`, `submit_test_cases`, `export_xray_csv` |
| Future (separate approval, dry-run by default) | `xray_create_tests`, `xray_link_tests_to_story` |

`get_run` returns its result as JSON text with no output schema. Its payload embeds
`StoryAnalysis`, whose computed risk severity can't appear in a validation-mode output schema
without also changing the input schema of `submit_story_analysis`.

## Errors

Anticipated failures return `isError: true` with the message `[<code>] <message>`. The codes
are defined in `src/qa_assistant/errors.py`:
- `not_configured`
- `not_implemented`
- `not_found`
- `invalid_artifact`
- `export_blocked`

When arguments violate a tool's schema (a bad issue key, unknown fields), the SDK rejects the
call with the Pydantic message.

## Safety properties

- **Jira reads are wrapped by `ProjectScopedJiraClient`.** `get_story` refuses keys outside
  `JIRA_PROJECT_KEY`. JQL is rewritten to `project = "KEY" AND (<user jql>)`, results are
  filtered again, and searches are capped at `JIRA_MAX_SEARCH_RESULTS`.
- **`run_id` is pattern-validated and path-contained**, so tool input can't escape
  `output/runs/`.
- **Domain models forbid unknown fields**, so a model can't smuggle data (for example raw CSV)
  into artifacts.
