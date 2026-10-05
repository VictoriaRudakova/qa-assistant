"""Domain-level errors.

Every error carries a stable machine-readable ``code``. Entry points (MCP server, future CLI)
translate these into user/LLM-facing messages; messages must never contain secrets.
"""

from __future__ import annotations


class QAAssistantError(Exception):
    """Base class for all anticipated errors."""

    code: str = "qa_assistant_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


class NotConfiguredError(QAAssistantError):
    """A required integration or setting is not configured."""

    code = "not_configured"


class NotImplementedYetError(QAAssistantError):
    """A capability is planned but not implemented in this phase."""

    code = "not_implemented"


class NotFoundError(QAAssistantError):
    """A requested entity (story, run, artifact) does not exist."""

    code = "not_found"


class InvalidArtifactError(QAAssistantError):
    """A submitted artifact failed blocking validation."""

    code = "invalid_artifact"


class ExportBlockedError(QAAssistantError):
    """Export refused, e.g. because the test cases have validation errors."""

    code = "export_blocked"


class JiraRequestError(QAAssistantError):
    """Jira could not serve a read (credentials, network, rate limit, bad JQL, server error)."""

    code = "jira_error"
