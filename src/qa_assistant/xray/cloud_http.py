"""Read-only transport for the Xray Cloud API (``/api/v2``).

Xray Cloud's API is GraphQL over ``POST``. Two requests exist here: ``authenticate`` (API key
-> bearer token) and :meth:`XrayCloudHttp.query`, which refuses any document that is not a
GraphQL ``query``, so no mutation can be sent. The token lives in memory only, is never
returned or logged, and is renewed once if Xray rejects it (it expires). Error messages never
contain credentials, the token or request headers.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import SecretStr

from qa_assistant import __version__
from qa_assistant.errors import XrayRequestError

logger = logging.getLogger(__name__)

AUTHENTICATE_PATH = "api/v2/authenticate"
GRAPHQL_PATH = "api/v2/graphql"
_MAX_ERROR_DETAIL = 300
_QUERY_RE = re.compile(r"^\s*query\b")


class XrayCloudHttp:
    """Authenticated GraphQL queries against one Xray Cloud endpoint."""

    def __init__(
        self,
        base_url: str,
        client_id: SecretStr,
        client_secret: SecretStr,
        *,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: SecretStr | None = None
        self._client = httpx.Client(
            base_url=base_url if base_url.endswith("/") else f"{base_url}/",
            timeout=timeout_seconds,
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": f"qa-assistant/{__version__}"},
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def query(self, document: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        """Run a GraphQL query and return its ``data`` object.

        Raises ``XrayRequestError`` for transport, HTTP and GraphQL errors.
        """
        if not _QUERY_RE.match(document):
            raise ValueError("Only GraphQL queries are allowed (read-only).")
        body = {"query": document, "variables": dict(variables)}
        response = self._post(GRAPHQL_PATH, body, auth=True)
        if response.status_code == httpx.codes.UNAUTHORIZED:  # expired token: renew once
            self._token = None
            response = self._post(GRAPHQL_PATH, body, auth=True)
        if response.status_code != httpx.codes.OK:
            raise _status_error(response)
        payload = _json(response)
        if not isinstance(payload, Mapping):
            raise XrayRequestError("Xray returned an unexpected GraphQL response.")
        if errors := payload.get("errors"):
            raise XrayRequestError(f"Xray rejected the query: {_graphql_errors(errors)}")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise XrayRequestError("Xray returned a GraphQL response without data.")
        return data

    # ------------------------------------------------------------------ internals

    def _post(self, path: str, body: Mapping[str, Any], *, auth: bool) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._bearer().get_secret_value()}"} if auth else {}
        try:
            response = self._client.post(path, json=body, headers=headers)
        except httpx.TimeoutException:
            raise XrayRequestError(
                f"Xray did not respond within {self.timeout_seconds:g}s."
            ) from None
        except httpx.HTTPError as exc:
            raise XrayRequestError(f"Could not reach Xray ({type(exc).__name__}).") from None
        logger.debug("POST %s -> HTTP %s", path, response.status_code)
        return response

    def _bearer(self) -> SecretStr:
        if self._token is None:
            self._token = self._authenticate()
        return self._token

    def _authenticate(self) -> SecretStr:
        response = self._post(
            AUTHENTICATE_PATH,
            {
                "client_id": self._client_id.get_secret_value(),
                "client_secret": self._client_secret.get_secret_value(),
            },
            auth=False,
        )
        if response.status_code in (httpx.codes.BAD_REQUEST, httpx.codes.UNAUTHORIZED):
            raise XrayRequestError(
                f"Xray rejected the API key (HTTP {response.status_code}). "
                "Check XRAY_CLIENT_ID / XRAY_CLIENT_SECRET and the Xray licence."
            )
        if response.status_code != httpx.codes.OK:
            raise _status_error(response)
        token = _json(response)  # a JSON string
        if not isinstance(token, str) or not token.strip():
            raise XrayRequestError("Xray authentication returned no token.")
        return SecretStr(token.strip())


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        raise XrayRequestError("Xray returned a non-JSON response.") from None


def _status_error(response: httpx.Response) -> XrayRequestError:
    status = response.status_code
    if status == httpx.codes.UNAUTHORIZED:
        return XrayRequestError("Xray rejected the token (HTTP 401) after re-authenticating.")
    if status == httpx.codes.FORBIDDEN:
        return XrayRequestError("Xray denied access (HTTP 403). Check the API key's user.")
    if status == httpx.codes.TOO_MANY_REQUESTS:
        return XrayRequestError("Xray rate limit reached (HTTP 429). Retry later.")
    if 300 <= status < 400:
        return XrayRequestError(
            f"Xray redirected the request (HTTP {status}). Check XRAY_CLOUD_BASE_URL."
        )
    return XrayRequestError(f"Xray returned HTTP {status}.")


def _graphql_errors(errors: Any) -> str:
    messages = [
        str(e.get("message")) if isinstance(e, Mapping) else str(e)
        for e in (errors if isinstance(errors, list) else [errors])
    ]
    return "; ".join(messages)[:_MAX_ERROR_DETAIL] or "unknown error"
