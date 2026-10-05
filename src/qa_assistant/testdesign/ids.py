from __future__ import annotations

from collections.abc import Sequence

from qa_assistant.domain.test_case import TestCase, TestCaseDraft


def assign_ids(drafts: Sequence[TestCaseDraft]) -> list[TestCase]:
    """Number drafts TC-001.. in submission order (stable for a given submission)."""
    return [
        TestCase(id=f"TC-{n:03d}", **draft.model_dump()) for n, draft in enumerate(drafts, start=1)
    ]
