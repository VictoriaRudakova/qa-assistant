---
name: design-test-cases
description: Design and submit manual test cases for an existing QA run (run_id from a previous story analysis). Use when an analysis exists and test cases are needed or must be regenerated.
argument-hint: <run_id>
---

# Design test cases for a run

1. If `$ARGUMENTS` is empty, call `list_runs` and ask which run to use.
2. Delegate to the `test-designer` subagent with the `run_id`.
3. Show the user the coverage matrix, test count, final revision and remaining warnings.
   Suggest `/review-test-cases <run_id>` next.
