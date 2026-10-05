"""Selects the Jira client implementation from settings."""

from __future__ import annotations

from typing import NoReturn

from qa_assistant.config.settings import JiraSettings
from qa_assistant.domain.story import JiraStory, StorySearchPage
from qa_assistant.errors import NotConfiguredError, NotImplementedYetError, QAAssistantError
from qa_assistant.jira.ports import JiraClient
from qa_assistant.jira.scoping import ProjectScopedJiraClient


class UnavailableJiraClient:
    """Stand-in used when no real client can be built; every call raises ``error``.

    Lets the MCP server start (and the non-Jira tools work) without Jira configured.
    """

    def __init__(self, error: QAAssistantError) -> None:
        self.error = error

    def _fail(self) -> NoReturn:
        raise self.error

    def get_story(self, issue_key: str, *, include_comments: bool = False) -> JiraStory:
        self._fail()

    def search_stories(
        self, jql: str, *, max_results: int, next_page_token: str | None = None
    ) -> StorySearchPage:
        self._fail()


def build_jira_client(settings: JiraSettings) -> JiraClient:
    """Return a project-scoped client, or an unavailable stand-in if not configured."""
    missing = settings.missing_settings()
    if missing or settings.project_key is None:
        return UnavailableJiraClient(
            NotConfiguredError(f"Jira is not configured. Missing: {', '.join(missing)}.")
        )
    # Phase 3 replaces this stand-in with the real HTTP client for the deployment.
    inner = UnavailableJiraClient(
        NotImplementedYetError("The Jira HTTP client is not implemented yet (planned: Phase 3).")
    )
    return ProjectScopedJiraClient(
        inner, settings.project_key, max_search_results=settings.max_search_results
    )
