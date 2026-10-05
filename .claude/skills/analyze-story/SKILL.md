---
name: analyze-story
description: QA analysis only - requirements, acceptance criteria gaps, ambiguities, risks and questions for the product owner - for a Jira story key, without designing tests. Use for refinement/grooming preparation.
argument-hint: <ISSUE-KEY>
---

# Analyze a story

1. Delegate to the `story-analyst` subagent with `$ARGUMENTS` (or pasted story text if Jira is
   not configured yet).
2. Present the result to the user as:
   - **Run:** `run_id` (reuse it later with `/design-test-cases <run_id>`)
   - **Acceptance criteria** (mark inferred ones)
   - **Questions for the PO** (findings of kind question / ambiguity / missing_requirement)
   - **Risks** sorted by severity, with category
   - **Assumptions / out of scope**
