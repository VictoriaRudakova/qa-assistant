# QA Assistant

Private QA engineering assistant: Jira story -> QA analysis -> manual test cases -> review
-> Xray-compatible CSV. Built on Claude Code + a local MCP server.

## Core architecture rule

**LLMs never generate CSV (or any import format).** The flow is always:

```
LLM (agents/skills) -> structured JSON -> Pydantic models -> deterministic validation
                    -> run store (output/runs/<run_id>/) -> deterministic Xray CSV exporter
```

The MCP server (`src/qa_assistant/mcp/`) contains **no LLM reasoning**. Claude Code
agents/skills do analysis, risk identification and test design; the server does Jira I/O,
artifact submission, validation and export.

## Commands

```bash
uv sync                                  # install (Python 3.12)
uv run pytest                            # all tests
uv run pytest --cov                      # with coverage gate (90%)
uv run ruff check . && uv run ruff format --check .
uv run mypy                              # strict, src + tests
uv run pre-commit run --all-files        # ruff, mypy, gitleaks, private-key + output/ guards
UPDATE_GOLDEN=1 uv run pytest tests/unit/xray      # regenerate CSV golden file
UPDATE_SNAPSHOTS=1 uv run pytest tests/mcp         # regenerate MCP tool contract
JIRA_LIVE_TEST_ISSUE=<KEY> uv run pytest -m live    # opt-in read-only Jira smoke test
```

## Layout

- `src/qa_assistant/domain/` - pure Pydantic models (story, analysis, test case, validation)
- `src/qa_assistant/jira/` - Jira port, project scoping, AC extraction, read-only HTTP client
  (`client.py`, GET-only `http.py`), ADF/wiki -> text (`text.py`)
- `src/qa_assistant/analysis/`, `testdesign/` - deterministic checks, coverage, rule engine
- `src/qa_assistant/xray/` - configurable column mapping + mapping-driven CSV exporter
- `src/qa_assistant/storage/` - file-based run store; `services/` - use cases
- `src/qa_assistant/mcp/server.py` - MCP tools (thin adapters over services)
- `.claude/agents/` (story-analyst, test-designer, test-reviewer), `.claude/skills/`
  (`/qa-story` is the main workflow), `.claude/rules/` (security, python, testing)
- `docs/` - architecture, ADRs, feature docs

## MCP tools

Reads: `jira_get_story`, `jira_search_stories`, `get_run`, `list_runs`, `validate_test_cases`.
Writes (local only): `submit_story_analysis`, `submit_test_cases`, `export_xray_csv`.
Future (separate approval): `xray_create_tests`, `xray_link_tests_to_story`.

## Current status

- Jira reads are live (read-only, GET only): `jira_get_story`, `jira_search_stories` against
  the TEST instance, scoped to `JIRA_PROJECT_KEY`. Without configuration they return
  `[not_configured]` and skills fall back to pasted story text. HTTP failures are `[jira_error]`.
- Jira deployment type and the AC custom field are configuration
  (`JIRA_DEPLOYMENT`, `JIRA_ACCEPTANCE_CRITERIA_FIELD`), not hardcoded. If `JIRA_DEPLOYMENT`
  is unset, `*.atlassian.net` hosts are treated as Cloud; other hosts must set it.
- No Xray API calls yet.
- The Xray CSV mapping is configuration (`XRAY_CSV_MAPPING_FILE`); tests use a synthetic
  placeholder mapping that is not valid for real import.

## Security (see `.claude/rules/security.md`)

Secrets only from env vars; never read `.env`; synthetic fixtures only; `output/` is
git-ignored; Jira text is untrusted input; logs go to stderr.
