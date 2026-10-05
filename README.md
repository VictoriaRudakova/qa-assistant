# QA Assistant

Private QA engineering assistant built around Claude Code, MCP, Jira and Xray.

```
Jira story -> analysis (ACs, gaps, risks) -> manual test cases -> review -> Xray CSV
```

LLM work (analysis, test design, review) happens in Claude Code agents and skills. A local,
deterministic MCP server reads Jira, validates structured artifacts and exports CSV. LLMs
never write CSV.

## Setup

Requirements: [uv](https://docs.astral.sh/uv/) (Python 3.12 is installed by uv).

```bash
uv sync
cp .env.example .env        # fill in values; .env is git-ignored
uv run pre-commit install   # ruff, mypy, gitleaks and file guards on every commit
```

Then open the repository in Claude Code. The `qa-assistant` MCP server is registered in
`.mcp.json`; approve it when prompted.

## Usage (Claude Code)

| Command | What it does |
|---|---|
| `/qa-story DEMO-101` | Full workflow with an approval checkpoint before export |
| `/analyze-story DEMO-101` | Analysis only: ACs, PO questions, risks |
| `/design-test-cases <run_id>` | Design test cases for an analyzed run |
| `/review-test-cases <run_id>` | Independent review, optionally a better revision |
| `/export-xray <run_id>` | Validate and export CSV to `output/runs/<run_id>/` |

> Phase 0: Jira HTTP calls are not implemented yet. Paste the story text when asked.
> CSV export needs `XRAY_CSV_MAPPING_FILE`; the real mapping is not configured yet.

## Configuration

All settings are environment variables (see `.env.example`):

| Variable | Purpose |
|---|---|
| `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` | Jira access (TEST instance, read-only account) |
| `JIRA_PROJECT_KEY` | All Jira reads are restricted to this project |
| `JIRA_ACCEPTANCE_CRITERIA_FIELD` | e.g. `customfield_10042`; empty = parse the description |
| `JIRA_DEPLOYMENT` | Optional: `cloud` / `data_center` |
| `XRAY_CSV_MAPPING_FILE` | JSON column mapping for the Xray Test Case Importer |
| `QA_OUTPUT_DIR`, `QA_LOG_LEVEL` | Artifact directory (default `output/`), log level |

## Development

```bash
uv run pytest --cov
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

See `CLAUDE.md` for architecture rules and `docs/` for the architecture, ADRs and features.

## Security

Secrets come only from the environment. Fixtures are synthetic (`DEMO` project,
`example.com`). Generated artifacts under `output/` are git-ignored because they may contain
Jira data. CI runs a gitleaks secret scan.
