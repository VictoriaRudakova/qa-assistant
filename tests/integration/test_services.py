from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.enums import AcceptanceCriterionSource, Readiness
from qa_assistant.domain.story import AcceptanceCriterion, JiraStory
from qa_assistant.domain.test_case import TestCaseDraft
from qa_assistant.errors import (
    ExportBlockedError,
    InvalidArtifactError,
    NotConfiguredError,
    NotFoundError,
)
from qa_assistant.jira.factory import UnavailableJiraClient
from qa_assistant.services.export import ExportService
from qa_assistant.services.runs import RunService
from qa_assistant.storage.run_store import RunStore
from qa_assistant.xray.csv_exporter import MappedXrayCsvExporter
from qa_assistant.xray.mapping import XrayCsvMapping
from tests.support import FIXTURES, RUN_ID, FakeJiraClient


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


def test_get_run_overview_before_and_after_test_cases(
    runs: RunService, analysis: StoryAnalysis, drafts: list[TestCaseDraft]
) -> None:
    run_id = runs.submit_story_analysis(analysis).run_id
    before = runs.get_run(run_id)
    assert before.acceptance_criterion_ids == ["AC-1", "AC-2", "AC-3", "AC-4"]
    assert (before.finding_ids, before.risk_ids) == (["F-1", "F-2"], ["R-1", "R-2"])
    assert (before.revision, before.test_case_count) == (None, 0)
    assert runs.get_story_analysis(run_id) == analysis

    runs.submit_test_cases(run_id, drafts[:4])
    drafts[0].status = Readiness.CLARIFICATION_REQUIRED
    drafts[0].open_question_ids = ["F-2"]
    runs.submit_test_cases(run_id, drafts)
    latest = runs.get_run(run_id)
    assert latest.manifest.latest_revision == 2
    assert (latest.revision, latest.test_case_count) == (2, 5)
    assert (latest.ready_count, latest.clarification_required_count) == (4, 1)
    assert runs.get_run(run_id, revision=1).test_case_count == 4


def test_list_and_get_test_cases_are_paged(
    runs: RunService, analysis: StoryAnalysis, drafts: list[TestCaseDraft]
) -> None:
    run_id = runs.submit_story_analysis(analysis).run_id
    runs.submit_test_cases(run_id, drafts)

    index = runs.list_test_cases(run_id, offset=0, limit=2)
    assert ([i.id for i in index.items], index.total, index.next_offset) == (
        ["TC-001", "TC-002"],
        5,
        2,
    )
    assert index.items[1].covers == ["AC-2"]
    assert index.items[1].step_count == 3
    last = runs.list_test_cases(run_id, offset=4, limit=2)
    assert ([i.id for i in last.items], last.next_offset) == (["TC-005"], None)

    page = runs.get_test_cases(run_id, offset=3, limit=10)
    assert [tc.id for tc in page.test_cases] == ["TC-004", "TC-005"]
    assert page.next_offset is None
    by_id = runs.get_test_cases(run_id, ids=["TC-005", "TC-001"], offset=3)
    assert [tc.id for tc in by_id.test_cases] == ["TC-005", "TC-001"]
    assert (by_id.offset, by_id.next_offset) == (0, None)
    with pytest.raises(NotFoundError, match="TC-099"):
        runs.get_test_cases(run_id, ids=["TC-099"])
    with pytest.raises(InvalidArtifactError, match="at most 25"):
        runs.get_test_cases(run_id, ids=[f"TC-{n:03d}" for n in range(1, 27)])


def test_large_run_is_readable_in_bounded_pages(
    runs: RunService, analysis: StoryAnalysis, drafts: list[TestCaseDraft]
) -> None:
    """200 verbose cases: every page stays small and paging returns every case once."""
    long_step = drafts[1].steps[0].model_copy(update={"expected_result": "x" * 400})
    big = [
        drafts[n % 5].model_copy(update={"title": f"Case {n}", "steps": [long_step] * 8})
        for n in range(200)
    ]
    run_id = runs.submit_story_analysis(analysis).run_id
    runs.submit_test_cases(run_id, big)

    seen: list[str] = []
    offset: int | None = 0
    while offset is not None:
        page = runs.get_test_cases(run_id, offset=offset, limit=25)
        assert len(page.model_dump_json()) < 120_000
        seen += [tc.id for tc in page.test_cases]
        offset = page.next_offset
    assert seen == [f"TC-{n:03d}" for n in range(1, 201)]

    index_pages: list[int] = []
    offset = 0
    while offset is not None:
        index = runs.list_test_cases(run_id, offset=offset, limit=100)
        assert len(index.model_dump_json()) < 40_000
        index_pages.append(len(index.items))
        offset = index.next_offset
    assert index_pages == [100, 100]
    assert len(runs.get_run(run_id).model_dump_json()) < 2_000


def test_analysis_must_match_jira_acceptance_criteria(
    store: RunStore, fake_jira: FakeJiraClient, analysis: StoryAnalysis
) -> None:
    runs = RunService(store, fake_jira)
    extra = analysis.model_copy(deep=True)
    extra.acceptance_criteria.append(
        AcceptanceCriterion(
            id="AC-5", text="Invented by the analyst.", source=AcceptanceCriterionSource.DESCRIPTION
        )
    )
    with pytest.raises(InvalidArtifactError, match="AC-5 is not in Jira"):
        runs.submit_story_analysis(extra)
    dropped = analysis.model_copy(deep=True)
    dropped.acceptance_criteria = dropped.acceptance_criteria[:3]
    with pytest.raises(InvalidArtifactError, match="AC-4 is missing"):
        runs.submit_story_analysis(dropped)
    assert store.list_runs() == []


def test_jira_wording_is_stored_for_acceptance_criteria(
    store: RunStore, fake_jira: FakeJiraClient, story: JiraStory, analysis: StoryAnalysis
) -> None:
    reworded = analysis.model_copy(deep=True)
    reworded.acceptance_criteria[0].text = "Reworded by the analyst."
    result = RunService(store, fake_jira).submit_story_analysis(reworded)
    assert [i.code for i in result.issues] == ["ANALYSIS_AC_TEXT_REPLACED"]
    stored = store.load_analysis(result.run_id)
    assert stored.acceptance_criteria == story.acceptance_criteria


def test_analysis_without_jira_is_accepted_but_flagged(
    store: RunStore, analysis: StoryAnalysis
) -> None:
    unavailable = UnavailableJiraClient(NotConfiguredError("Jira is not configured."))
    result = RunService(store, unavailable).submit_story_analysis(analysis)
    assert [i.code for i in result.issues] == ["ANALYSIS_ACS_UNVERIFIED"]


def test_export_refuses_cases_that_need_clarification(
    runs: RunService, export: ExportService, analysis: StoryAnalysis, drafts: list[TestCaseDraft]
) -> None:
    drafts.append(
        drafts[2].model_copy(
            update={
                "title": "Reusing a reset link follows the agreed rule",
                "status": Readiness.CLARIFICATION_REQUIRED,
                "covers": [],
                "finding_ids": ["F-1"],
                "open_question_ids": ["F-1"],
            }
        )
    )
    run_id = runs.submit_story_analysis(analysis).run_id
    report = runs.submit_test_cases(run_id, drafts).report
    assert (report.valid, report.export_ready) == (True, False)
    assert report.clarification_required_test_case_ids == ["TC-006"]
    with pytest.raises(ExportBlockedError, match="CLARIFICATION_REQUIRED: TC-006"):
        export.export_xray_csv(run_id)

    result = export.export_xray_csv(run_id, ready_only=True)
    assert (result.test_case_count, result.excluded_test_case_ids) == (5, ["TC-006"])
    assert "TC-006" not in Path(result.path).read_text(encoding="utf-8")
    assert (
        Path(result.path).read_bytes()
        == (FIXTURES / "xray" / "DEMO-101.synthetic.csv").read_bytes()
    )


def test_ready_only_export_still_needs_full_ac_coverage(
    runs: RunService, export: ExportService, analysis: StoryAnalysis, drafts: list[TestCaseDraft]
) -> None:
    drafts[4].status = Readiness.CLARIFICATION_REQUIRED  # the only AC-4 case
    drafts[4].open_question_ids = ["F-2"]
    run_id = runs.submit_story_analysis(analysis).run_id
    report = runs.submit_test_cases(run_id, drafts).report
    assert "AC_ONLY_CLARIFICATION_COVERAGE" in {i.code for i in report.warnings}
    with pytest.raises(ExportBlockedError, match=r"after leaving out .*AC_NOT_COVERED"):
        export.export_xray_csv(run_id, ready_only=True)


def test_ready_only_export_with_no_ready_cases(
    runs: RunService, export: ExportService, analysis: StoryAnalysis, drafts: list[TestCaseDraft]
) -> None:
    for draft in drafts:
        draft.status = Readiness.CLARIFICATION_REQUIRED
        draft.open_question_ids = ["F-2"]
    run_id = runs.submit_story_analysis(analysis).run_id
    runs.submit_test_cases(run_id, drafts)
    with pytest.raises(ExportBlockedError, match="no ready test cases"):
        export.export_xray_csv(run_id, ready_only=True)


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
