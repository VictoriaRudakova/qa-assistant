"""Opt-in, read-only smoke test against the configured TEST Jira.

Run explicitly (never part of normal runs or CI, which deselect ``live``)::

    JIRA_LIVE_TEST_ISSUE=DEMO-1 uv run pytest -m live

Requires the ``JIRA_*`` configuration (environment or the git-ignored ``.env``) plus
``JIRA_LIVE_TEST_ISSUE``, an issue key inside ``JIRA_PROJECT_KEY``; skips otherwise.

Safety:
* every request passes through :class:`GetOnlyTransport`, which refuses anything but GET;
* assertions compare booleans and issue keys only, so a failure never prints credentials,
  account details or story content.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

from qa_assistant.config.settings import (
    DEFAULT_ENV_FILE,
    JiraDeployment,
    JiraSettings,
    load_settings,
)
from qa_assistant.domain.base import IssueKey
from qa_assistant.jira.factory import build_jira_client, jira_auth, resolve_deployment
from qa_assistant.jira.http import JiraHttp

pytestmark = pytest.mark.live


class LiveTestSettings(BaseSettings):
    """``JIRA_LIVE_TEST_*`` variables (test-only; not part of the application settings)."""

    model_config = SettingsConfigDict(
        env_prefix="JIRA_LIVE_TEST_", extra="ignore", env_ignore_empty=True
    )

    issue: IssueKey | None = None


class GetOnlyTransport(httpx.HTTPTransport):
    """Real network transport that records methods and rejects every non-GET request."""

    def __init__(self) -> None:
        super().__init__()
        self.methods: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.methods.append(request.method)
        if request.method != "GET":
            raise AssertionError(f"live Jira test attempted a {request.method} request")
        return super().handle_request(request)


@pytest.fixture
def jira() -> JiraSettings:
    settings = load_settings().jira
    missing = settings.missing_settings()
    if missing:
        pytest.skip(f"live Jira not configured; missing: {', '.join(missing)}")
    return settings


@pytest.fixture
def issue_key() -> str:
    issue = LiveTestSettings(_env_file=DEFAULT_ENV_FILE).issue
    if issue is None:
        pytest.skip("set JIRA_LIVE_TEST_ISSUE to an issue key in JIRA_PROJECT_KEY")
    return issue


@pytest.fixture
def transport() -> Iterator[GetOnlyTransport]:
    guard = GetOnlyTransport()
    yield guard
    guard.close()


def test_myself_authenticates(jira: JiraSettings, transport: GetOnlyTransport) -> None:
    deployment = resolve_deployment(jira)
    api = "rest/api/3" if deployment is JiraDeployment.CLOUD else "rest/api/2"
    http = JiraHttp(
        str(jira.base_url),
        jira_auth(jira, deployment),
        timeout_seconds=jira.timeout_seconds,
        transport=transport,
    )
    try:
        me = http.get_json(f"{api}/myself", not_found="Jira /myself endpoint not found.")
    finally:
        http.close()

    active = isinstance(me, dict) and me.get("active") is True
    assert active, "authenticated, but the Jira account is not active"
    assert transport.methods == ["GET"]


def test_fetch_configured_issue(
    jira: JiraSettings, issue_key: str, transport: GetOnlyTransport
) -> None:
    client = build_jira_client(jira, transport=transport)
    story = client.get_story(issue_key)

    assert story.key == issue_key
    has_summary = bool(story.summary)
    assert has_summary
    assert transport.methods
    assert set(transport.methods) == {"GET"}
