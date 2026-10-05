from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.story import JiraStory
from qa_assistant.domain.test_case import TestCaseDraft, TestCaseSet
from qa_assistant.storage.run_store import RunStore
from qa_assistant.testdesign.ids import assign_ids
from qa_assistant.xray.mapping import XrayCsvMapping
from tests.support import FIXED_NOW, FIXTURES, RUN_ID, FakeJiraClient, load_json


@pytest.fixture(autouse=True)
def _isolated_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never see real JIRA_*/XRAY_*/QA_* configuration from the developer's shell.

    Exception: opt-in ``live`` tests, which exist to use that configuration.
    """
    if request.node.get_closest_marker("live"):
        return
    for name in list(os.environ):
        if name.startswith(("JIRA_", "XRAY_", "QA_")):
            monkeypatch.delenv(name)


@pytest.fixture
def story() -> JiraStory:
    return JiraStory.model_validate(load_json("jira/DEMO-101.story.json"))


@pytest.fixture
def analysis_data() -> dict[str, Any]:
    data: dict[str, Any] = load_json("analysis/DEMO-101.analysis.json")
    return data


@pytest.fixture
def analysis(analysis_data: dict[str, Any]) -> StoryAnalysis:
    return StoryAnalysis.model_validate(analysis_data)


@pytest.fixture
def drafts_data() -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = load_json("test_cases/DEMO-101.drafts.json")
    return data


@pytest.fixture
def drafts(drafts_data: list[dict[str, Any]]) -> list[TestCaseDraft]:
    return [TestCaseDraft.model_validate(d) for d in drafts_data]


@pytest.fixture
def test_set(drafts: list[TestCaseDraft]) -> TestCaseSet:
    return TestCaseSet(
        run_id=RUN_ID,
        story_key="DEMO-101",
        revision=1,
        created_at=FIXED_NOW,
        test_cases=assign_ids(drafts),
    )


@pytest.fixture
def synthetic_mapping() -> XrayCsvMapping:
    return XrayCsvMapping.from_file(FIXTURES / "xray" / "synthetic_mapping.json")


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path / "output", clock=lambda: FIXED_NOW, id_factory=lambda _: RUN_ID)


@pytest.fixture
def fake_jira(story: JiraStory) -> FakeJiraClient:
    return FakeJiraClient([story])
