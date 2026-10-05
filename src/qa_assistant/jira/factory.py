"""Selects the Jira client implementation from settings."""

from __future__ import annotations

from typing import NoReturn

import httpx

from qa_assistant.config.settings import JiraDeployment, JiraSettings
from qa_assistant.domain.story import JiraStory, StorySearchPage
from qa_assistant.errors import NotConfiguredError, QAAssistantError
from qa_assistant.jira.client import HttpJiraClient
from qa_assistant.jira.http import BearerAuth, JiraHttp
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


def resolve_deployment(settings: JiraSettings) -> JiraDeployment:
    """``JIRA_DEPLOYMENT`` if set; otherwise Cloud for ``*.atlassian.net`` hosts."""
    if settings.deployment is not None:
        return settings.deployment
    host = settings.base_url.host if settings.base_url else None
    if host and host.endswith(".atlassian.net"):
        return JiraDeployment.CLOUD
    raise NotConfiguredError(
        "JIRA_DEPLOYMENT (cloud | data_center) cannot be inferred from JIRA_BASE_URL; set it."
    )


def jira_auth(settings: JiraSettings, deployment: JiraDeployment) -> httpx.Auth:
    """Basic auth (email + API token) on Cloud; bearer personal access token on Data Center."""
    if settings.api_token is None:
        raise NotConfiguredError("Jira is not configured. Missing: JIRA_API_TOKEN.")
    if deployment is JiraDeployment.CLOUD:
        return httpx.BasicAuth(settings.email or "", settings.api_token.get_secret_value())
    return BearerAuth(settings.api_token)


def build_jira_client(
    settings: JiraSettings, *, transport: httpx.BaseTransport | None = None
) -> JiraClient:
    """Return a project-scoped read-only client, or an unavailable stand-in if not configured.

    ``transport`` is for tests (``httpx.MockTransport``); production uses the network.
    """
    missing = settings.missing_settings()
    if (
        missing
        or settings.base_url is None
        or settings.api_token is None
        or settings.project_key is None
    ):
        return UnavailableJiraClient(
            NotConfiguredError(f"Jira is not configured. Missing: {', '.join(missing)}.")
        )
    try:
        deployment = resolve_deployment(settings)
    except NotConfiguredError as exc:
        return UnavailableJiraClient(exc)

    base_url = str(settings.base_url)
    http = JiraHttp(
        base_url,
        jira_auth(settings, deployment),
        timeout_seconds=settings.timeout_seconds,
        transport=transport,
    )
    inner = HttpJiraClient(
        http,
        deployment=deployment,
        browse_base_url=base_url,
        acceptance_criteria_field=settings.acceptance_criteria_field,
    )
    return ProjectScopedJiraClient(
        inner, settings.project_key, max_search_results=settings.max_search_results
    )
