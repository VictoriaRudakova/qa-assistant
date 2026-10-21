# MCP tools

Server name: `qa-assistant` (stdio). In Claude Code the tools appear as `mcp__qa-assistant__<tool>`.

**Source of truth:**
- Exact input and output schemas: `tests/mcp/snapshots/tool_schemas.json` (pinned by tests).
- Behaviour: `src/qa_assistant/mcp/server.py`, which delegates to `src/qa_assistant/services/`.

This page doesn't copy those schemas.

## Tools by kind

| Kind | Tools |
|---|---|
| Jira reads (project-scoped) | `jira_get_story`, `jira_search_stories` |
| Local reads | `get_run`, `get_story_analysis`, `list_test_cases`, `get_test_cases`, `get_coverage`, `list_runs`, `validate_test_cases` |
| Local writes (`output/runs/` only) | `submit_story_analysis`, `submit_test_cases`, `export_xray_csv` |
| Future (separate approval, dry-run by default) | `xray_create_tests`, `xray_link_tests_to_story` |

## Reading a run in sections

No read tool returns a payload that grows without bound, so agents never need filesystem
access to read a run, however many test cases it has:

| Tool | Returns | Bound |
|---|---|---|
| `get_run` | manifest, AC/finding/risk ids, test-case counts by readiness | fixed size |
| `get_story_analysis` | the full `StoryAnalysis` | one story |
| `list_test_cases` | index rows (id, title, status, traceability, step count), no steps | `limit` ≤ 100 |
| `get_test_cases` | full cases with steps, by `ids` or by page | ≤ 25 per call |
| `get_coverage` | `CoverageReport`: Jira AC coverage (all / ready cases), finding and risk coverage, readiness ids; no issues | ACs + findings + risks |
| `validate_test_cases` | `ValidationReport`: issues, AC/finding/risk coverage, readiness | per revision |

Paged tools return `total` and `next_offset`; follow `next_offset` until it is `null`.

## Revising test cases

Every `submit_test_cases` call stores a complete new revision, but a revision does not
have to be re-sent in full: `keep_ids` names cases of `keep_from_revision` that the server
copies verbatim (content and traceability), followed by `test_cases` (new or rewritten
cases). Every revision is still stored in full and validated as a whole, so readiness
rules and export gates apply to kept cases exactly as to re-sent ones.

| Rule | Why |
|---|---|
| `keep_from_revision` is required with `keep_ids` and must be the run's latest revision (older: `invalid_artifact` "stale"; unknown: `not_found`) | A caller working from an old revision cannot discard newer changes |
| Unknown or duplicate `keep_ids` are refused; nothing is stored | No guessing |
| A kept case may not also be re-sent with the same (normalized) title | A replacement must not silently leave the old case in place |
| `not_kept` lists every base case that is not kept (replaced or dropped) | Deletions are explicit in the result |
| Ids are assigned TC-001.. in order: kept cases in `keep_ids` order, then `test_cases`; `kept` maps old to new ids | Deterministic renumbering, as for a full resubmission |

In recorded live runs 69% of resubmitted bytes were unchanged cases, which the agent had
to generate again as output tokens (`python -m evals --resubmit-savings` replays stored runs
and reports this; legacy runs that predate the schema are listed as skipped and are not
in the totals).

Known limits:
- **Semantic review.** The server checks structure, not intent. A replacement under a
  *new* title while the old case is still kept is accepted; only the agent checking
  `not_kept` (and the reviewer) catches it. Whether a kept case is still the right test is
  a review judgement.
- **Concurrent writes.** The run store has no lock. The stale check covers a caller using
  an old base, but two simultaneous submissions to one run can race; the server is meant
  for one local user. A full resubmission (no `keep_ids`) has no stale check.

`get_story_analysis` returns JSON text with no output schema: `StoryAnalysis` has a computed
risk severity that can't appear in a validation-mode output schema without also changing the
input schema of `submit_story_analysis`.

## Acceptance criteria and readiness

- `submit_story_analysis` re-fetches the story when Jira is configured. The analysis must
  carry exactly the Jira AC ids (`ANALYSIS_NON_JIRA_AC`, `ANALYSIS_DROPPED_AC` are errors)
  and the stored ACs use Jira's wording. Without Jira the result carries the
  `ANALYSIS_ACS_UNVERIFIED` warning. Gaps are findings, never ACs. Reworded ACs
  (`ANALYSIS_AC_TEXT_REPLACED`) and duplicate Jira ACs without a finding relating them
  (`ANALYSIS_DUPLICATE_AC`) are warnings.
- Test cases trace to Jira ACs (`covers`), risks (`risk_ids`) and findings (`finding_ids`).
  The report's `coverage` (ACs), `finding_coverage` (gaps/questions) and `risk_coverage`
  are separate; only `coverage` counts as AC coverage. A ready case that traces only to
  findings is an error (`TC_READY_GAP_ONLY`) and blocks export.
- Each case has `status`: `ready` or `clarification_required` (with `open_question_ids`).
  `valid` means no errors; `export_ready` additionally needs no `clarification_required`
  case. `export_xray_csv` refuses a revision that is not export-ready; `ready_only=true`
  leaves those cases out, and the remaining set must still validate (including AC
  coverage). A case that needs clarification is never written to a CSV.

## Errors

Anticipated failures return `isError: true` with the message `[<code>] <message>`. The codes
are defined in `src/qa_assistant/errors.py`:
- `not_configured`
- `not_implemented`
- `jira_error`: Jira auth failure, network error or timeout, rate limit, rejected JQL, or a server error
- `not_found`
- `invalid_artifact`
- `export_blocked`

When arguments violate a tool's schema (a bad issue key, unknown fields), the SDK rejects the
call with the Pydantic message.

## Safety properties

- **Jira text is untrusted.** `jira_get_story` lists instruction-like sections in
  `untrusted_instructions` (a tripwire; see `jira/untrusted.py`). The server never acts on
  story text, and AC, readiness and export checks hold whatever the text says.
- **Jira reads are wrapped by `ProjectScopedJiraClient`.** `get_story` refuses keys outside
  `JIRA_PROJECT_KEY`. JQL is rewritten to `project = "KEY" AND (<user jql>)`, results are
  filtered again, and searches are capped at `JIRA_MAX_SEARCH_RESULTS`.
- **`run_id` is pattern-validated and path-contained**, so tool input can't escape
  `output/runs/`.
- **Domain models forbid unknown fields**, so a model can't smuggle data (for example raw CSV)
  into artifacts.
