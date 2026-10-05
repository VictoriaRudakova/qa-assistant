from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from qa_assistant.config.settings import JiraDeployment, JiraSettings, load_settings


def test_defaults_without_environment() -> None:
    settings = load_settings(env_file=None)
    assert settings.jira.base_url is None
    assert settings.jira.acceptance_criteria_field is None
    assert settings.app.output_dir == Path("output")
    assert settings.secret_values() == []
    assert set(settings.jira.missing_settings()) == {
        "JIRA_BASE_URL",
        "JIRA_EMAIL",
        "JIRA_API_TOKEN",
        "JIRA_PROJECT_KEY",
    }


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://jira.example.com")
    monkeypatch.setenv("JIRA_EMAIL", "qa.bot@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "not-a-real-token-123")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "DEMO")
    monkeypatch.setenv("JIRA_ACCEPTANCE_CRITERIA_FIELD", "customfield_10042")
    monkeypatch.setenv("XRAY_CSV_MAPPING_FILE", "config/mapping.json")

    settings = load_settings(env_file=None)

    assert settings.jira.missing_settings() == []
    assert settings.jira.acceptance_criteria_field == "customfield_10042"
    assert settings.xray.csv_mapping_file == Path("config/mapping.json")
    assert settings.secret_values() == ["not-a-real-token-123"]


def test_token_is_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_API_TOKEN", "not-a-real-token-123")
    settings = load_settings(env_file=None)
    assert "not-a-real-token-123" not in repr(settings)
    assert "not-a-real-token-123" not in settings.model_dump_json()


def test_reads_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("JIRA_PROJECT_KEY=DEMO\nQA_LOG_LEVEL=DEBUG\n", encoding="utf-8")
    settings = load_settings(env_file=env_file)
    assert settings.jira.project_key == "DEMO"
    assert settings.app.log_level == "DEBUG"


def test_env_example_loads_and_blank_values_mean_unset() -> None:
    """The committed template must be loadable as-is (blank optional values = not set)."""
    settings = load_settings(env_file=Path(__file__).parents[3] / ".env.example")
    assert settings.jira.project_key == "DEMO"
    assert settings.jira.acceptance_criteria_field is None
    assert settings.jira.deployment is None
    assert settings.jira.api_token is None
    assert settings.xray.csv_mapping_file is None
    assert settings.jira.missing_settings() == ["JIRA_API_TOKEN"]


def test_data_center_does_not_require_email() -> None:
    jira = JiraSettings.model_validate(
        {
            "base_url": "https://jira.example.com",
            "api_token": "fake-pat",
            "project_key": "DEMO",
            "deployment": JiraDeployment.DATA_CENTER,
        }
    )
    assert jira.missing_settings() == []


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JIRA_ACCEPTANCE_CRITERIA_FIELD", "Acceptance Criteria"),
        ("JIRA_PROJECT_KEY", "demo"),
        ("JIRA_DEPLOYMENT", "server"),
        ("JIRA_MAX_SEARCH_RESULTS", "500"),
    ],
)
def test_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        load_settings(env_file=None)
