"""Jira adapter interface.

Implementations (Cloud / Data Center) are selected by ``JIRA_DEPLOYMENT`` and must:
* be read-only;
* normalize the description (ADF on Cloud, wiki markup on DC) to plain text using the
  conventions documented in :mod:`qa_assistant.jira.acceptance_criteria`;
* populate ``JiraStory.acceptance_criteria`` via
  :func:`qa_assistant.jira.acceptance_criteria.extract_acceptance_criteria`.
"""

from __future__ import annotations

from typing import Protocol

from qa_assistant.domain.story import JiraStory, StorySearchPage


class JiraClient(Protocol):
    def get_story(self, issue_key: str, *, include_comments: bool = False) -> JiraStory:
        """Fetch one issue. Raises ``NotFoundError`` if it does not exist."""
        ...

    def search_stories(
        self, jql: str, *, max_results: int, next_page_token: str | None = None
    ) -> StorySearchPage:
        """Run a JQL search. Implementations must enforce ``max_results``."""
        ...
