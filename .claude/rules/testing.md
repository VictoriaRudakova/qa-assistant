---
paths:
  - "tests/**"
---

# Testing rules

- `tests/unit`: pure logic. `tests/integration`: run store + services on `tmp_path`.
  `tests/mcp`: in-process MCP client, tool contract snapshot, stdio smoke test.
- Shared helpers live in `tests/support.py` (never import from `conftest.py`).
- Fixtures in `tests/fixtures/` are synthetic only (see `.claude/rules/security.md`).
- Golden files: `tests/fixtures/xray/*.csv` (`UPDATE_GOLDEN=1`) and
  `tests/mcp/snapshots/tool_schemas.json` (`UPDATE_SNAPSHOTS=1`). Regenerate only for an
  intentional change and review the diff.
- No network in tests. Real Jira/Xray tests live in `tests/live/`, are marked
  `@pytest.mark.live`, skip when not configured, are GET-only, and never run in CI (pytest
  deselects `live` by default; opt in with `JIRA_LIVE_TEST_ISSUE=<KEY> uv run pytest -m live`).
- Coverage gate: 90% (branch). Run `uv run pytest --cov`.
