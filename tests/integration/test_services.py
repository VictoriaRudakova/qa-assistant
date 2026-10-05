from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.test_case import TestCaseDraft
from qa_assistant.errors import (
    ExportBlockedError,
    InvalidArtifactError,
    NotConfiguredError,
    NotFoundError,
)
from qa_assistant.services.export import ExportService
from qa_assistant.services.runs import RunService
from qa_assistant.storage.run_store import RunStore
from qa_assistant.xray.csv_exporter import MappedXrayCsvExporter
from qa_assistant.xray.mapping import XrayCsvMapping
from tests.support import FIXTURES, RUN_ID


@pytest.fixture
def runs(store: RunStore) -> RunService:
    return RunService(store)


@pytest.fixture
def export(store: RunStore, synthetic_mapping: XrayCsvMapping) -> ExportService:
    return ExportService(store, MappedXrayCsvExporter(synthetic_mapping))


def test_submit_analysis_starts_run(runs: RunService, analysis: StoryAnalysis) -> None:
    result = runs.submit_story_analysis(analysis)
    assert result.run_id == RUN_ID
    assert result.story_key == "DEMO-101"
    assert result.issues == []


def test_submit_analysis_rejects_broken_references(
    runs: RunService, store: RunStore, analysis: StoryAnalysis
) -> None:
    analysis.risks[0].related_ac_ids = ["AC-77"]
    with pytest.raises(InvalidArtifactError, match="AC-77"):
        runs.submit_story_analysis(analysis)
    assert store.list_runs() == []


def test_full_flow_exports_golden_csv(
    runs: RunService,
    export: ExportService,
    analysis: StoryAnalysis,
    drafts: list[TestCaseDraft],
) -> None:
    run_id = runs.submit_story_analysis(analysis).run_id
    submitted = runs.submit_test_cases(run_id, drafts)
    assert (submitted.revision, submitted.test_case_count, submitted.report.valid) == (1, 5, True)

    result = export.export_xray_csv(run_id)

    data = Path(result.path).read_bytes()
    assert data == (FIXTURES / "xray" / "DEMO-101.synthetic.csv").read_bytes()
    assert result.sha256 == hashlib.sha256(data).hexdigest()
    assert (result.rows, result.test_case_count, result.revision) == (9, 5, 1)
    assert "synthetic placeholder" in result.warnings[0]


def test_invalid_revision_is_stored_but_export_blocked(
    runs: RunService, export: ExportService, analysis: StoryAnalysis, drafts: list[TestCaseDraft]
) -> None:
    run_id = runs.submit_story_analysis(analysis).run_id
    first = runs.submit_test_cases(run_id, drafts[:4])  # AC-4 uncovered
    assert not first.report.valid
    with pytest.raises(ExportBlockedError, match="AC_NOT_COVERED"):
        export.export_xray_csv(run_id)

    second = runs.submit_test_cases(run_id, drafts)
    assert (second.revision, second.report.valid) == (2, True)
    assert export.export_xray_csv(run_id).revision == 2
    with pytest.raises(ExportBlockedError):
        export.export_xray_csv(run_id, revision=1)


def test_export_refuses_overwrite_unless_asked(
    runs: RunService, export: ExportService, analysis: StoryAnalysis, drafts: list[TestCaseDraft]
) -> None:
    run_id = runs.submit_story_analysis(analysis).run_id
    runs.submit_test_cases(run_id, drafts)
    export.export_xray_csv(run_id)
    with pytest.raises(ExportBlockedError, match="already exists"):
        export.export_xray_csv(run_id)
    assert export.export_xray_csv(run_id, overwrite=True).revision == 1


def test_export_without_mapping_is_not_configured(
    store: RunStore, runs: RunService, analysis: StoryAnalysis, drafts: list[TestCaseDraft]
) -> None:
    run_id = runs.submit_story_analysis(analysis).run_id
    runs.submit_test_cases(run_id, drafts)
    with pytest.raises(NotConfiguredError, match="XRAY_CSV_MAPPING_FILE"):
        ExportService(store, None).export_xray_csv(run_id)


def test_revalidate_stored_revision(
    runs: RunService, analysis: StoryAnalysis, drafts: list[TestCaseDraft]
) -> None:
    run_id = runs.submit_story_analysis(analysis).run_id
    runs.submit_test_cases(run_id, drafts)
    assert runs.validate_test_cases(run_id).valid


def test_get_run_before_and_after_test_cases(
    runs: RunService, analysis: StoryAnalysis, drafts: list[TestCaseDraft]
) -> None:
    run_id = runs.submit_story_analysis(analysis).run_id
    before = runs.get_run(run_id)
    assert before.analysis == analysis
    assert before.test_cases is None

    runs.submit_test_cases(run_id, drafts[:4])
    runs.submit_test_cases(run_id, drafts)
    latest = runs.get_run(run_id)
    assert latest.manifest.latest_revision == 2
    assert latest.test_cases is not None
    assert (latest.test_cases.revision, len(latest.test_cases.test_cases)) == (2, 5)
    first = runs.get_run(run_id, revision=1).test_cases
    assert first is not None
    assert len(first.test_cases) == 4


def test_get_run_unknown_revision(runs: RunService, analysis: StoryAnalysis) -> None:
    run_id = runs.submit_story_analysis(analysis).run_id
    with pytest.raises(NotFoundError, match="no submitted test cases"):
        runs.get_run(run_id, revision=1)


def test_list_runs_filters_and_limits(tmp_path: Path, analysis: StoryAnalysis) -> None:
    ids = iter(["20261005T120000Z-000001", "20261005T130000Z-000002", "20261005T140000Z-000003"])
    runs = RunService(RunStore(tmp_path, id_factory=lambda _: next(ids)))
    for _ in range(3):
        runs.submit_story_analysis(analysis)
    assert [m.run_id[-1] for m in runs.list_runs()] == ["3", "2", "1"]
    assert [m.run_id[-1] for m in runs.list_runs(limit=2)] == ["3", "2"]
    assert runs.list_runs("DEMO-999") == []
