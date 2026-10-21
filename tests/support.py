"""Shared test helpers (importable from test modules, unlike conftest)."""

from __future__ import annotations

import copy
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from qa_assistant.domain.story import (
    JiraIssueIdentity,
    JiraStory,
    JiraStorySummary,
    StorySearchPage,
)
from qa_assistant.errors import NotFoundError

FIXTURES = Path(__file__).parent / "fixtures"
FIXED_NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
RUN_ID = "20261005T120000Z-abc123"


def load_json(relative: str) -> Any:
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


class FakeJiraClient:
    """In-memory :class:`~qa_assistant.jira.ports.JiraClient` for tests."""

    def __init__(
        self, stories: list[JiraStory], identities: Sequence[JiraIssueIdentity] = ()
    ) -> None:
        self.stories = {s.key: s for s in stories}
        self.identities = {i.key: i for i in identities}
        self.last_jql: str | None = None
        self.last_max_results: int | None = None

    def get_issue_identity(self, issue_key: str) -> JiraIssueIdentity:
        try:
            return self.identities[issue_key]
        except KeyError:
            raise NotFoundError(f"Issue {issue_key} does not exist.") from None

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


XRAY_CLIENT_ID = "fake-xray-client-id"
XRAY_CLIENT_SECRET = "fake-xray-client-secret-for-tests"
XRAY_TOKEN = "fake-xray-bearer-token-for-tests"
# What the configured Jira says about the Test in the Xray fixture (same site: same ids).
DEMO_201_IDENTITY = JiraIssueIdentity(
    key="DEMO-201", issue_id="10201", project_id="10000", project_key="DEMO"
)


def xray_test_response(**test_overrides: Any) -> dict[str, Any]:
    """The synthetic ``getTests`` response for DEMO-201, with fields of the Test replaced."""
    body: dict[str, Any] = copy.deepcopy(load_json("xray/DEMO-201.get_tests.json"))
    body["data"]["getTests"]["results"][0].update(test_overrides)
    return body


class XrayRouter:
    """MockTransport handler for Xray Cloud: ``authenticate`` returns a token, every
    GraphQL request is answered by the next queued response. Records all requests."""

    def __init__(self, *graphql: httpx.Response, auth: httpx.Response | None = None) -> None:
        self.graphql = list(graphql)
        self.auth = auth or httpx.Response(200, json=XRAY_TOKEN)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/api/v2/authenticate"):
            return self.auth
        return self.graphql.pop(0)

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]
