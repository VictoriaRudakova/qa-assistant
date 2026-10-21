"""Builds the read-only Xray Cloud client from settings."""

from __future__ import annotations

from typing import NoReturn

import httpx

from qa_assistant.config.settings import JiraDeployment, Settings
from qa_assistant.domain.xray import XrayTest
from qa_assistant.errors import NotConfiguredError, QAAssistantError
from qa_assistant.jira.factory import UnavailableJiraClient
from qa_assistant.jira.ports import JiraClient
from qa_assistant.xray.cloud_client import CloudXrayClient
from qa_assistant.xray.cloud_http import XrayCloudHttp
from qa_assistant.xray.ports import XrayTestReader


class UnavailableXrayClient:
    """Stand-in used when Xray is not configured; every call raises ``error``."""

    def __init__(self, error: QAAssistantError) -> None:
        self.error = error

    def get_test(self, issue_key: str, *, step_offset: int = 0) -> XrayTest:
        self._fail()

    def _fail(self) -> NoReturn:
        raise self.error


def build_xray_client(
    settings: Settings, jira_client: JiraClient, *, transport: httpx.BaseTransport | None = None
) -> XrayTestReader:
    """Return a project-scoped read-only Xray Cloud client, or an unavailable stand-in.

    Needs ``XRAY_CLIENT_ID``, ``XRAY_CLIENT_SECRET``, the Jira project scope
    (``JIRA_PROJECT_KEY``) and a configured ``jira_client``: every Test is verified against
    Jira's issue and project ids, so without Jira nothing is read (fail closed). Xray Cloud
    only runs on Jira Cloud, so ``JIRA_DEPLOYMENT=data_center`` is refused. ``transport``
    is for tests (``httpx.MockTransport``).
    """
    if isinstance(jira_client, UnavailableJiraClient):
        return UnavailableXrayClient(
            NotConfiguredError(
                "Xray reads are verified against Jira (tenant identity), but "
                f"{jira_client.error.message}"
            )
        )
    xray, jira = settings.xray, settings.jira
    missing = xray.missing_settings() + (["JIRA_PROJECT_KEY"] if jira.project_key is None else [])
    if missing or xray.client_id is None or xray.client_secret is None or not jira.project_key:
        return UnavailableXrayClient(
            NotConfiguredError(f"Xray Cloud is not configured. Missing: {', '.join(missing)}.")
        )
    if jira.deployment is JiraDeployment.DATA_CENTER:
        return UnavailableXrayClient(
            NotConfiguredError(
                "Xray Cloud needs Jira Cloud, but JIRA_DEPLOYMENT is data_center "
                "(Xray Server/Data Center is not supported)."
            )
        )
    http = XrayCloudHttp(
        str(xray.cloud_base_url),
        xray.client_id,
        xray.client_secret,
        timeout_seconds=xray.timeout_seconds,
        transport=transport,
    )
    return CloudXrayClient(
        http,
        jira=jira_client,
        project_key=jira.project_key,
        browse_base_url=str(jira.base_url) if jira.base_url else None,
    )
