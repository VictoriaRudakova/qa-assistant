# ADR 0003: Configurable Xray CSV column mapping

- Status: Accepted
- Date: 2026-10-05

## Context

Xray Cloud and Data Center import CSV differently, and the Test Case Importer's column
mapping is configured per instance. The target instance and its importer configuration are
not known yet.

## Decision

- Test cases are stored only as the internal `TestCase`/`TestStep` model.
- `XrayCsvExporter` is a protocol (`render(TestCaseSet) -> RenderedCsv(text, rows)`,
  deterministic). The exporter reports its own row count, so callers never assume a layout.
- `MappedXrayCsvExporter` renders any `XrayCsvMapping` loaded from the JSON file named by
  `XRAY_CSV_MAPPING_FILE`. Layout: one row per step, grouped by a `test_case_id` column.
- Tests use `tests/fixtures/xray/synthetic_mapping.json` (`synthetic: true`) and a golden
  CSV file.
- The production mapping will be added once a sanitized importer CSV/config is provided,
  together with its own golden test.

## Consequences

- No hardcoded headers. Switching Cloud/DC means changing configuration, not code.
- If the real importer needs a layout the mapping cannot express, a second `XrayCsvExporter`
  implementation can be added behind the same protocol.
