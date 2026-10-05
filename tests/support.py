"""Shared test helpers (importable from test modules, unlike conftest)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qa_assistant.domain.story import JiraStory, JiraStorySummary, StorySearchPage
from qa_assistant.errors import NotFoundError

FIXTURES = Path(__file__).parent / "fixtures"
FIXED_NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
RUN_ID = "20261005T120000Z-abc123"


def load_json(relative: str) -> Any:
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


class FakeJiraClient:
    """In-memory :class:`~qa_assistant.jira.ports.JiraClient` for tests."""

    def __init__(self, stories: list[JiraStory]) -> None:
        self.stories = {s.key: s for s in stories}
        self.last_jql: str | None = None
        self.last_max_results: int | None = None

    def get_story(self, issue_key: str, *, include_comments: bool = False) -> JiraStory:
        try:
            return self.stories[issue_key]
        except KeyError:
            raise NotFoundError(f"Issue {issue_key} does not exist.") from None

    def search_stories(
        self, jql: str, *, max_results: int, next_page_token: str | None = None
    ) -> StorySearchPage:
        self.last_jql = jql
        self.last_max_results = max_results
        summaries = [
            JiraStorySummary(key=s.key, summary=s.summary, issue_type=s.issue_type, status=s.status)
            for s in self.stories.values()
        ]
        return StorySearchPage(issues=summaries[:max_results])
