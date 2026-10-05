from __future__ import annotations

import pytest

from qa_assistant.config.settings import JiraSettings
from qa_assistant.domain.story import JiraStory, JiraStorySummary, StorySearchPage
from qa_assistant.errors import NotConfiguredError, NotFoundError
from qa_assistant.jira.factory import UnavailableJiraClient, build_jira_client
from qa_assistant.jira.scoping import ProjectScopedJiraClient, issue_in_project, scope_jql
from tests.support import FakeJiraClient


@pytest.mark.parametrize(
    ("jql", "expected"),
    [
        ("", 'project = "DEMO"'),
        ("status = Done", 'project = "DEMO" AND (status = Done)'),
        ("a = 1 OR project = OTHER", 'project = "DEMO" AND (a = 1 OR project = OTHER)'),
        (
            "status = Done ORDER BY created DESC",
            'project = "DEMO" AND (status = Done) ORDER BY created DESC',
        ),
        ("order by key", 'project = "DEMO" ORDER BY key'),
    ],
)
def test_scope_jql(jql: str, expected: str) -> None:
    assert scope_jql(jql, "DEMO") == expected


@pytest.mark.parametrize(
    ("key", "inside"), [("DEMO-1", True), ("DEMOX-1", False), ("OTHER-1", False)]
)
def test_issue_in_project(key: str, inside: bool) -> None:
    assert issue_in_project(key, "DEMO") is inside


def test_scoped_client_blocks_other_projects(fake_jira: FakeJiraClient) -> None:
    client = ProjectScopedJiraClient(fake_jira, "DEMO", max_search_results=50)
    assert client.get_story("DEMO-101").key == "DEMO-101"
    with pytest.raises(NotFoundError, match="outside the configured Jira project"):
        client.get_story("OTHER-1")


def test_scoped_client_scopes_and_filters_search(story: JiraStory) -> None:
    foreign = story.model_copy(update={"key": "OTHER-7"})
    inner = FakeJiraClient([story, foreign])
    client = ProjectScopedJiraClient(inner, "DEMO", max_search_results=50)
    page = client.search_stories("status = Done", max_results=10)
    assert inner.last_jql == 'project = "DEMO" AND (status = Done)'
    assert [i.key for i in page.issues] == ["DEMO-101"]


def test_scoped_client_caps_search_results(fake_jira: FakeJiraClient) -> None:
    client = ProjectScopedJiraClient(fake_jira, "DEMO", max_search_results=5)
    client.search_stories("", max_results=100)
    assert fake_jira.last_max_results == 5
    client.search_stories("", max_results=3)
    assert fake_jira.last_max_results == 3


def test_factory_passes_search_cap_from_settings() -> None:
    settings = JiraSettings.model_validate(
        {
            "base_url": "https://jira.example.com",
            "email": "qa.bot@example.com",
            "api_token": "not-a-real-token",
            "project_key": "DEMO",
            "deployment": "cloud",
            "max_search_results": 7,
        }
    )
    client = build_jira_client(settings)
    assert isinstance(client, ProjectScopedJiraClient)
    assert client.max_search_results == 7


def test_unavailable_client_raises_its_error() -> None:
    client = UnavailableJiraClient(NotConfiguredError("nope"))
    with pytest.raises(NotConfiguredError):
        client.get_story("DEMO-1")
    with pytest.raises(NotConfiguredError):
        client.search_stories("", max_results=1)


def test_factory_reports_missing_settings() -> None:
    client = build_jira_client(JiraSettings(_env_file=None))
    with pytest.raises(NotConfiguredError, match="JIRA_BASE_URL"):
        client.get_story("DEMO-1")


def test_factory_configured_is_scoped_before_any_request() -> None:
    settings = JiraSettings.model_validate(
        {
            "base_url": "https://jira.example.com",
            "email": "qa.bot@example.com",
            "api_token": "not-a-real-token",
            "project_key": "DEMO",
            "deployment": "cloud",
        }
    )
    client = build_jira_client(settings)
    assert isinstance(client, ProjectScopedJiraClient)
    with pytest.raises(NotFoundError):
        client.get_story("OTHER-1")  # rejected before the HTTP client is reached


def test_search_page_model_copy_keeps_token() -> None:
    page = StorySearchPage(
        issues=[JiraStorySummary(key="DEMO-1", summary="s", issue_type="Story", status="Open")],
        next_page_token="abc",
    )
    client = ProjectScopedJiraClient(_Static(page), "DEMO", max_search_results=50)
    assert client.search_stories("", max_results=5).next_page_token == "abc"


class _Static:
    def __init__(self, page: StorySearchPage) -> None:
        self.page = page

    def get_story(self, issue_key: str, *, include_comments: bool = False) -> JiraStory:
        raise NotImplementedError

    def search_stories(
        self, jql: str, *, max_results: int, next_page_token: str | None = None
    ) -> StorySearchPage:
        return self.page
