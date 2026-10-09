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

ACs are numbered `AC-1..n`. Only Jira ACs are authoritative: the analyst never adds ACs, and
`submit_story_analysis` rejects an analysis whose AC ids differ from Jira's. Missing behaviour
is recorded as a finding (gap or question) and tests that explore it reference it through
`finding_ids`, reported separately from AC coverage.

## Readiness

A test case whose expected behaviour depends on an unanswered product question is
`clarification_required` and names the findings in `open_question_ids`. Such cases are kept
for traceability but block final export validation (`export_ready: false`) and are never
exported. Ready cases may not contain undecided expected results ("either ... or",
"record which", "TBD", "agreed with the PO", an `open-question-*` label):
`TC_UNRESOLVED_EXPECTED_RESULT` is an error. A ready case that traces only to findings
(no AC, no risk) asserts unspecified behaviour: `TC_READY_GAP_ONLY` is an error, so it blocks
export until the case is `clarification_required` or traces to a Jira AC or risk.

Guardrail placement, hooks and evals: `docs/architecture/harness.md`,
`docs/features/evals.md`.

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
- AC custom field id of the TEST instance, if ACs live outside the description.
