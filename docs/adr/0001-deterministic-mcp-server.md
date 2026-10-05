# ADR 0001: Deterministic MCP server, LLM reasoning in Claude Code

- Status: Accepted
- Date: 2026-10-05

## Context

Tools like `analyze_story` and `generate_test_cases` could either call an LLM inside the MCP
server, or receive results produced by the LLM that is already driving Claude Code.

## Decision

The MCP server contains no LLM reasoning. Claude Code agents and skills perform story
analysis, risk identification, test design and review. The server:

- reads Jira (read-only, project-scoped),
- accepts structured artifacts (`submit_story_analysis`, `submit_test_cases`),
- validates them deterministically,
- exports files (`export_xray_csv`),
- later writes to Xray.

Naming: read operations keep read-style names (`jira_get_story`, `jira_search_stories`,
`get_run`, `list_runs`, `validate_test_cases`). Persisting operations use `submit_*`, and
exports use `export_*`.

## Consequences

- No Anthropic API key or prompt logic in the server, and the server is fully unit-testable.
- The Pydantic schemas are the contract the LLM must satisfy: tool input schemas force
  structure, and `extra="forbid"` rejects anything else.
- Reasoning quality is improved by editing agents and skills, not server code.
