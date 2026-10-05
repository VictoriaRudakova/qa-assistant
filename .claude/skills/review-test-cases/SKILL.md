---
name: review-test-cases
description: Independent critical review of the submitted test cases of a QA run, optionally submitting an improved revision. Use before exporting to Xray or when the user asks to review/improve generated tests.
argument-hint: <run_id>
---

# Review test cases

1. If `$ARGUMENTS` is empty, call `list_runs` and ask which run to review.
2. Delegate to the `test-reviewer` subagent with the `run_id`.
3. Relay the verdict, the changes made (by test id) and the PO questions. If the verdict is
   "ready", suggest `/export-xray <run_id>`.
