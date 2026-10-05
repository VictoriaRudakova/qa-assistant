"""Read-only HTTP transport for the Jira REST API.

Only ``GET`` exists here: there is deliberately no method that could create, update,
transition or comment on an issue. Failures become :class:`~qa_assistant.errors` errors whose
messages never contain credentials or request headers.
"""

from __future__ import annotations

import logging
from collections.abc import Generator, Mapping
from typing import Any

import httpx
from pydantic import SecretStr

from qa_assistant import __version__
from qa_assistant.errors import JiraRequestError, NotFoundError

logger = logging.getLogger(__name__)

_MAX_ERROR_DETAIL = 500


class BearerAuth(httpx.Auth):
    """``Authorization: Bearer`` (Jira Data Center personal access token)."""

    def __init__(self, token: SecretStr) -> None:
        self._token = token

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._token.get_secret_value()}"
        yield request


class JiraHttp:
    """GET-only JSON access to one Jira instance."""

    def __init__(
        self,
        base_url: str,
        auth: httpx.Auth,
        *,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self._client = httpx.Client(
            base_url=base_url if base_url.endswith("/") else f"{base_url}/",
            auth=auth,
            timeout=timeout_seconds,
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": f"qa-assistant/{__version__}"},
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def get_json(
        self, path: str, params: Mapping[str, str | int] | None = None, *, not_found: str
    ) -> Any:
        """GET ``path`` (relative to the base URL) and return the decoded JSON body.

        Raises ``NotFoundError(not_found)`` on 404 and ``JiraRequestError`` otherwise.
        """
        try:
            response = self._client.get(path, params=dict(params or {}))
        except httpx.TimeoutException:
            raise JiraRequestError(
                f"Jira did not respond within {self.timeout_seconds:g}s."
            ) from None
        except httpx.HTTPError as exc:
            raise JiraRequestError(f"Could not reach Jira ({type(exc).__name__}).") from None

        logger.debug("GET %s -> HTTP %s", path, response.status_code)
        if response.status_code == httpx.codes.OK:
            try:
                return response.json()
            except ValueError:
                raise JiraRequestError("Jira returned a non-JSON response.") from None
        raise _status_error(response, not_found)


def _status_error(response: httpx.Response, not_found: str) -> Exception:
    status = response.status_code
    if status == httpx.codes.NOT_FOUND:
        return NotFoundError(not_found)
    if status == httpx.codes.UNAUTHORIZED:
        return JiraRequestError(
            "Jira rejected the credentials (HTTP 401). Check JIRA_EMAIL / JIRA_API_TOKEN."
        )
    if status == httpx.codes.FORBIDDEN:
        return JiraRequestError("Jira denied access (HTTP 403). Check the account's permissions.")
    if status == httpx.codes.TOO_MANY_REQUESTS:
        return JiraRequestError("Jira rate limit reached (HTTP 429). Retry later.")
    if status == httpx.codes.BAD_REQUEST:
        detail = _error_detail(response)
        return JiraRequestError(f"Jira rejected the request (HTTP 400){detail}")
    if 300 <= status < 400:
        return JiraRequestError(
            f"Jira redirected the request (HTTP {status}). Check JIRA_BASE_URL."
        )
    return JiraRequestError(f"Jira returned HTTP {status}.")


def _error_detail(response: httpx.Response) -> str:
    """Jira's own error messages (e.g. JQL syntax errors), truncated."""
    try:
        body = response.json()
    except ValueError:
        return "."
    messages: list[str] = []
    if isinstance(body, Mapping):
        raw_messages = body.get("errorMessages")
        if isinstance(raw_messages, list):
            messages.extend(str(m) for m in raw_messages)
        errors = body.get("errors")
        if isinstance(errors, Mapping):
            messages.extend(f"{k}: {v}" for k, v in errors.items())
    if not messages:
        return "."
    return ": " + "; ".join(messages)[:_MAX_ERROR_DETAIL]
