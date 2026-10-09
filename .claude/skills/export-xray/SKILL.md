---
name: export-xray
description: Validate and export the latest (or a given) revision of a QA run to Xray-compatible CSV via the deterministic exporter. Use when the user asks to export test cases for Xray import.
argument-hint: <run_id> [revision]
disable-model-invocation: true
---

# Export to Xray CSV

The CSV is produced only by the `export_xray_csv` MCP tool from validated, stored test cases.
Never write or edit CSV yourself.

1. Call `validate_test_cases` for the run (and revision, if given). If `valid` is false, list
   the errors and stop; suggest `/design-test-cases` or `/review-test-cases`. If
   `export_ready` is false, list the `clarification_required` cases and their open
   questions; export them only after the PO answers, or export the ready cases with
   `ready_only=true` if the user explicitly asks for that.
2. Show the warnings and ask the user to confirm the export.
3. Call `export_xray_csv`. Report `path`, `rows`, `test_case_count`, `sha256`, `mapping_name`
   and every warning. If the mapping is the synthetic placeholder, state clearly that the
   file is **not** importable into the real Xray instance.
4. If the tool returns `[not_configured]`, explain that `XRAY_CSV_MAPPING_FILE` must point to
   the reviewed Xray column mapping (see `docs/features/story-to-xray-csv.md`).
