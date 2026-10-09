"""Offline :class:`~qa_assistant.jira.ports.JiraClient` serving synthetic stories from files.

Used only when ``JIRA_FIXTURES_DIR`` is set: the live-agent evals point a dedicated MCP
server at a directory of ``<KEY>.json`` files (serialized :class:`JiraStory`), so the real
``/qa-story`` workflow runs end to end without touching a Jira instance. It is read-only and
is still wrapped by :class:`~qa_assistant.jira.scoping.ProjectScopedJiraClient`.
"""

from __future__ import annotations

from pathlib import Path

from qa_assistant.domain.base import IssueKey
from qa_assistant.domain.story import JiraStory, JiraStorySummary, StorySearchPage
from qa_assistant.errors import NotFoundError
from qa_assistant.jira.untrusted import with_untrusted_flags


class FixtureJiraClient:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def get_story(self, issue_key: IssueKey, *, include_comments: bool = False) -> JiraStory:
        path = self._directory / f"{issue_key}.json"
        if path.parent != self._directory or not path.is_file():
            raise NotFoundError(f"Issue {issue_key} does not exist.")
        story = JiraStory.model_validate_json(path.read_text(encoding="utf-8"))
        if not include_comments:
            story = story.model_copy(update={"comments": []})
        return with_untrusted_flags(story)

    def search_stories(
        self, jql: str, *, max_results: int, next_page_token: str | None = None
    ) -> StorySearchPage:
        stories = [
            JiraStory.model_validate_json(p.read_text(encoding="utf-8"))
            for p in sorted(self._directory.glob("*.json"))
        ]
        return StorySearchPage(
            issues=[
                JiraStorySummary(
                    key=s.key, summary=s.summary, issue_type=s.issue_type, status=s.status
                )
                for s in stories[:max_results]
            ]
        )
