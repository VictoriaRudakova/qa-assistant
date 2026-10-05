---
paths:
  - "src/**/*.py"
---

# Python rules for `src/`

- Python 3.12, `from __future__ import annotations`, full type hints; `mypy --strict` must pass.
- Layering (imports only flow downward):
  `mcp` -> `services` -> (`jira`, `analysis`, `testdesign`, `xray`, `storage`) -> `domain`.
  `domain` imports nothing from the package except itself. `config` and `errors` are leaves.
- The MCP layer contains no business logic and **no LLM reasoning**. Tools are thin wrappers
  over services; anticipated failures raise `QAAssistantError` subclasses (stable `code`).
- Domain models extend `DomainModel` (`extra="forbid"`). Computed values use
  `@computed_field` and are never accepted as input.
- Models whose class names start with `Test` set `__test__: ClassVar[bool] = False`.
- Tool names: reads `jira_*` / `get_*` / `list_*` / `validate_*`; persisting `submit_*`; files
  `export_*`. Changing a tool's schema changes the public contract: update
  `tests/mcp/snapshots/tool_schemas.json` deliberately (`UPDATE_SNAPSHOTS=1`).
- Validator rule codes are a contract used by skills/agents; do not rename them.
- CSV is produced only by `qa_assistant.xray`; the column mapping comes from configuration.
