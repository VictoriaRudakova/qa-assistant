# ADR 0002: File-based run store; tools pass run ids, not payloads

- Status: Accepted
- Date: 2026-10-05

## Context

If an export tool accepted test cases as an argument, the LLM could alter or retype them
between validation and export. Large payloads round-tripping through the context are also
error-prone.

## Decision

Every `submit_*` call persists validated JSON under `output/runs/<run_id>/`. Each test-case
submission is a complete new revision (`test_cases.r<N>.json`). Later tools take `run_id`
(and optionally `revision`). `export_xray_csv` reads the stored revision and re-validates it
before rendering. Validation reports are recomputed whenever they're needed, never stored, so
no stale copy can exist. Agents read runs through the MCP read tools, so the on-disk layout
stays an implementation detail.

Run ids look like `YYYYMMDDTHHMMSSZ-xxxxxx`, are pattern-validated, and resolve only inside
the store directory. Writes are atomic (temp file + rename).

## Consequences

- Export is provably derived from validated data.
- Full revision history supports review loops and auditing.
- `output/` may contain Jira data and is git-ignored.
