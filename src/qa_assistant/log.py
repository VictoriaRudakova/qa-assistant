"""Logging setup.

Rules:
* Logs go to **stderr only**. stdout is the MCP stdio transport; writing to it corrupts the
  protocol.
* Credentials are redacted: known secret values plus anything that looks like an HTTP
  ``Authorization`` header value.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable

REDACTED = "***REDACTED***"

_AUTH_HEADER_RE = re.compile(r"(?i)\b(authorization\s*[:=]\s*)(\S+(?:\s+\S+)?)")
_SCHEME_TOKEN_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Return ``text`` with secret values and auth header values replaced."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    text = _AUTH_HEADER_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    return _SCHEME_TOKEN_RE.sub(lambda m: f"{m.group(1)} {REDACTED}", text)


class RedactingFilter(logging.Filter):
    """Redacts secrets from the fully formatted log message."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = tuple(s for s in secrets if s)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact(message, self._secrets)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


def configure_logging(level: str = "INFO", secrets: Iterable[str] = ()) -> None:
    """Configure the root logger to write redacted records to stderr."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter(secrets))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
