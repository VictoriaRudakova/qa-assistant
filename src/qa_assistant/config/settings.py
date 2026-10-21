"""Application settings.

All configuration (and every secret) comes from environment variables, optionally loaded
from a git-ignored ``.env`` file. Nothing here has a secret default. See ``.env.example``.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ENV_FILE = Path(".env")

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class JiraDeployment(StrEnum):
    CLOUD = "cloud"
    DATA_CENTER = "data_center"


class JiraSettings(BaseSettings):
    """``JIRA_*`` variables.

    Deployment type and AC field are deliberately not hardcoded: ``JIRA_DEPLOYMENT`` is optional
    (to be auto-detected or set once the target instance is confirmed) and
    ``JIRA_ACCEPTANCE_CRITERIA_FIELD`` falls back to the issue description when unset.
    """

    model_config = SettingsConfigDict(env_prefix="JIRA_", extra="ignore", env_ignore_empty=True)

    base_url: HttpUrl | None = None
    # Account email for basic auth (Jira Cloud). Not needed for a Data Center PAT.
    email: str | None = None
    # Jira Cloud API token, or Data Center personal access token.
    api_token: SecretStr | None = None
    # Every read is scoped to this project (guard against reading outside the test project).
    project_key: Annotated[str | None, Field(pattern=r"^[A-Z][A-Z0-9_]+$")] = None
    # e.g. "customfield_10042". When unset, ACs are extracted from the description.
    acceptance_criteria_field: Annotated[str | None, Field(pattern=r"^customfield_\d+$")] = None
    deployment: JiraDeployment | None = None
    max_search_results: Annotated[int, Field(ge=1, le=100)] = 50
    timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 30.0
    # Evals only: serve synthetic stories from <dir>/<KEY>.json instead of a Jira instance.
    fixtures_dir: Path | None = None

    def missing_settings(self) -> list[str]:
        """Names of env vars still required before a Jira client can be built."""
        missing: list[str] = []
        if self.base_url is None:
            missing.append("JIRA_BASE_URL")
        if self.deployment is not JiraDeployment.DATA_CENTER and not self.email:
            missing.append("JIRA_EMAIL")
        if self.api_token is None:
            missing.append("JIRA_API_TOKEN")
        if self.project_key is None:
            missing.append("JIRA_PROJECT_KEY")
        return missing


# Global Xray Cloud endpoint; data-residency tenants set a regional one
# (e.g. https://eu.xray.cloud.getxray.app).
DEFAULT_XRAY_CLOUD_URL = "https://xray.cloud.getxray.app"


class XraySettings(BaseSettings):
    """``XRAY_*`` variables. The CSV column mapping is a JSON file, never hardcoded.

    Xray Cloud reads use an API key (client id + secret). The project scope is Jira's
    (``JIRA_PROJECT_KEY``); Xray has no scope setting of its own.
    """

    model_config = SettingsConfigDict(env_prefix="XRAY_", extra="ignore", env_ignore_empty=True)

    csv_mapping_file: Path | None = None
    cloud_base_url: HttpUrl = HttpUrl(DEFAULT_XRAY_CLOUD_URL)
    client_id: SecretStr | None = None
    client_secret: SecretStr | None = None
    timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 30.0

    @field_validator("cloud_base_url")
    @classmethod
    def _https_only(cls, url: HttpUrl) -> HttpUrl:
        if url.scheme != "https":
            raise ValueError("XRAY_CLOUD_BASE_URL must use https")
        return url

    def missing_settings(self) -> list[str]:
        """Names of env vars still required before an Xray Cloud client can be built."""
        missing: list[str] = []
        if self.client_id is None:
            missing.append("XRAY_CLIENT_ID")
        if self.client_secret is None:
            missing.append("XRAY_CLIENT_SECRET")
        return missing


class AppSettings(BaseSettings):
    """``QA_*`` variables."""

    model_config = SettingsConfigDict(env_prefix="QA_", extra="ignore", env_ignore_empty=True)

    output_dir: Path = Path("output")
    log_level: LogLevel = "INFO"


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    jira: JiraSettings
    xray: XraySettings
    app: AppSettings

    def secret_values(self) -> list[str]:
        """Secret values to redact from logs."""
        secrets = (self.jira.api_token, self.xray.client_id, self.xray.client_secret)
        return [s.get_secret_value() for s in secrets if s]


def load_settings(env_file: Path | None = DEFAULT_ENV_FILE) -> Settings:
    """Load settings from the environment (and ``env_file`` if it exists)."""
    return Settings(
        jira=JiraSettings(_env_file=env_file),
        xray=XraySettings(_env_file=env_file),
        app=AppSettings(_env_file=env_file),
    )
