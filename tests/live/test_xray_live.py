"""Opt-in, read-only smoke test against the configured Xray Cloud and Jira.

Run explicitly (never part of normal runs or CI, which deselect ``live``)::

    XRAY_LIVE_TEST_ISSUE=<KEY> uv run pytest -m live tests/live/test_xray_live.py -s

Requires the ``JIRA_*`` configuration, ``XRAY_CLIENT_ID`` and ``XRAY_CLIENT_SECRET``
(environment or the git-ignored ``.env``) plus ``XRAY_LIVE_TEST_ISSUE``, a Test issue key
inside ``JIRA_PROJECT_KEY``; skips otherwise.

Safety:
* Jira requests pass through a GET-only transport; Xray requests through
  :class:`ReadOnlyXrayTransport`, which allows only ``authenticate`` and GraphQL ``query``
  documents (no mutation);
* assertions and the printed summary use keys, counts and booleans only, so neither a
  failure nor the output shows credentials, the token or Test content.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import httpx
import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

from qa_assistant.config.settings import DEFAULT_ENV_FILE, Settings, load_settings
from qa_assistant.domain.base import IssueKey
from qa_assistant.jira.factory import UnavailableJiraClient, build_jira_client
from qa_assistant.xray.cloud_http import AUTHENTICATE_PATH, GRAPHQL_PATH
from qa_assistant.xray.factory import build_xray_client

pytestmark = pytest.mark.live


class LiveXrayTestSettings(BaseSettings):
    """``XRAY_LIVE_TEST_*`` variables (test-only; not part of the application settings)."""

    model_config = SettingsConfigDict(
        env_prefix="XRAY_LIVE_TEST_", extra="ignore", env_ignore_empty=True
    )

    issue: IssueKey | None = None


class ReadOnlyXrayTransport(httpx.HTTPTransport):
    """Real network transport that records paths and refuses anything but reads."""

    def __init__(self) -> None:
        super().__init__()
        self.paths: list[str] = []
        self.documents: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.lstrip("/")
        self.paths.append(path)
        if request.method != "POST" or path not in (AUTHENTICATE_PATH, GRAPHQL_PATH):
            raise AssertionError(f"live Xray test attempted {request.method} {path}")
        if path == GRAPHQL_PATH:
            document = str(json.loads(request.content).get("query", ""))
            self.documents.append(document)
            if not document.lstrip().startswith("query"):
                raise AssertionError("live Xray test attempted a non-query GraphQL request")
        return super().handle_request(request)


class GetOnlyTransport(httpx.HTTPTransport):
    def __init__(self) -> None:
        super().__init__()
        self.methods: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.methods.append(request.method)
        if request.method != "GET":
            raise AssertionError(f"live test attempted a Jira {request.method} request")
        return super().handle_request(request)


@pytest.fixture
def settings() -> Settings:
    loaded = load_settings()
    missing = loaded.xray.missing_settings() + loaded.jira.missing_settings()
    if missing:
        pytest.skip(f"live Xray not configured; missing: {', '.join(missing)}")
    return loaded


@pytest.fixture
def issue_key() -> str:
    issue = LiveXrayTestSettings(_env_file=DEFAULT_ENV_FILE).issue
    if issue is None:
        pytest.skip("set XRAY_LIVE_TEST_ISSUE to a Test issue key in JIRA_PROJECT_KEY")
    return issue


@pytest.fixture
def transports() -> Iterator[tuple[GetOnlyTransport, ReadOnlyXrayTransport]]:
    jira, xray = GetOnlyTransport(), ReadOnlyXrayTransport()
    yield jira, xray
    jira.close()
    xray.close()


def test_read_configured_test(
    settings: Settings,
    issue_key: str,
    transports: tuple[GetOnlyTransport, ReadOnlyXrayTransport],
    caplog: pytest.LogCaptureFixture,
) -> None:
    jira_transport, xray_transport = transports
    caplog.set_level(logging.DEBUG)

    jira = build_jira_client(settings.jira, transport=jira_transport)
    assert not isinstance(jira, UnavailableJiraClient), "Jira client is not configured"
    xray = build_xray_client(settings, jira, transport=xray_transport)
    test = xray.get_test(issue_key)  # raises on any tenant identity mismatch
    identity = jira.get_issue_identity(issue_key)

    # identity: same issue and project in Jira and Xray
    assert test.key == issue_key
    same_issue = (test.issue_id, test.project_id) == (identity.issue_id, identity.project_id)
    assert same_issue, "Xray and Jira ids differ"
    # content parsed
    has_type = bool(test.test_type.name and test.test_type.kind)
    assert has_type
    expected_results = sum(1 for s in test.steps if s.expected_result)
    if test.test_type.kind == "Steps":
        assert test.steps, "a step Test returned no steps"
        assert expected_results, "no step has an expected result"
    assert len(test.steps) <= test.steps_total
    assert len(test.requirements) <= test.requirements_total
    # read-only
    assert set(jira_transport.methods) == {"GET"}
    assert xray_transport.paths[0] == AUTHENTICATE_PATH
    assert set(xray_transport.paths) <= {AUTHENTICATE_PATH, GRAPHQL_PATH}
    assert all(d.lstrip().startswith("query") for d in xray_transport.documents)
    assert not any("mutation" in d for d in xray_transport.documents)
    # nothing sensitive in the raw (unredacted) logs: secrets, a bearer header, Test content
    secrets_logged = any(s in caplog.text for s in settings.secret_values())
    bearer_logged = "bearer " in caplog.text.lower()
    content = [test.summary, *(t for s in test.steps for t in (s.action, s.expected_result))]
    content_logged = any(len(t) > 3 and t in caplog.text for t in content)
    assert not secrets_logged, "a credential appeared in the logs"
    assert not bearer_logged, "an authorization header appeared in the logs"
    assert not content_logged, "Test content appeared in the logs"

    in_project = sum(r.in_project for r in test.requirements)
    print(  # noqa: T201 - the smoke summary: counts and booleans only
        f"\nLIVE XRAY SMOKE: key_matches=True ids_match={same_issue} "
        f"type_kind={test.test_type.kind} steps={len(test.steps)}/{test.steps_total} "
        f"expected_results={expected_results} next_step_offset={test.next_step_offset} "
        f"requirements={len(test.requirements)}/{test.requirements_total} "
        f"in_project={in_project} untrusted_flags={len(test.untrusted_instructions)} "
        f"xray_requests={len(xray_transport.paths)} jira_requests={len(jira_transport.methods)} "
        f"log_lines={len(caplog.records)}"
    )
