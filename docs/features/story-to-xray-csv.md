# Feature: Jira story to Xray CSV

## Goal

Turn one Jira story into reviewed manual test cases and an Xray Test Case Importer CSV, with
traceability from every test case to acceptance criteria (and risks).

## Workflow

`/qa-story <KEY>` -> fetch -> `story-analyst` -> `test-designer` -> `test-reviewer` ->
user checkpoint -> `export_xray_csv`.

## Acceptance criteria source

1. `JIRA_ACCEPTANCE_CRITERIA_FIELD` (e.g. `customfield_10042`) when set and non-empty.
2. Otherwise the description's "Acceptance Criteria" section (markdown `#`, wiki `h3.`, bold
   line, or `Acceptance criteria:`), split into bullets, numbered items, paragraphs or
   Gherkin scenarios. See `jira/acceptance_criteria.py`.

ACs are numbered `AC-1..n`. The analyst may add inferred ACs (`source: inferred`).

## CSV mapping (configuration)

The exporter is mapping-driven. `XRAY_CSV_MAPPING_FILE` points to JSON like
`tests/fixtures/xray/synthetic_mapping.json`:

| Field | Meaning |
|---|---|
| `columns[]` | `{header, source, value?}`. Sources: `test_case_id` (required, groups step rows), `title`, `objective`, `preconditions`, `priority`, `labels`, `components`, `story_key`, `constant`, `step_number`, `step_action`, `step_data`, `step_expected_result` |
| `priority_map` | internal priority -> Jira priority name |
| `delimiter`, `encoding`, `line_terminator` | CSV dialect |
| `multi_value_separator`, `multiline_separator` | joins labels/components; preconditions |
| `repeat_test_fields_on_every_row` | default `false`: test fields on the first step row only |
| `synthetic` | `true` marks placeholders; export then warns it is not importable |

Cells are sanitized against formula injection (`= + - @` prefixes get `'`, except plain
numbers) and control characters.

## Open inputs (before production use)

- Xray flavour (Cloud vs Data Center) and a **sanitized** Test Case Importer CSV/config, to
  write the real mapping file and a golden test for it.
- Jira deployment type and AC custom field id of the TEST instance (Phase 3).
