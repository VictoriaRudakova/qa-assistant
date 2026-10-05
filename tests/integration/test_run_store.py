from __future__ import annotations

from pathlib import Path

import pytest

from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.test_case import TestCaseSet
from qa_assistant.errors import InvalidArtifactError, NotFoundError
from qa_assistant.storage.run_store import RUN_ID_RE, RunStore, new_run_id
from tests.support import FIXED_NOW, RUN_ID


def test_new_run_id_format() -> None:
    assert RUN_ID_RE.match(new_run_id(FIXED_NOW))
    assert new_run_id(FIXED_NOW).startswith("20261005T120000Z-")


def test_create_and_round_trip_artifacts(
    store: RunStore, analysis: StoryAnalysis, test_set: TestCaseSet
) -> None:
    manifest = store.create_run("DEMO-101")
    assert manifest.run_id == RUN_ID
    store.save_analysis(RUN_ID, analysis)
    assert store.load_analysis(RUN_ID) == analysis

    store.save_test_cases(test_set)
    assert store.load_test_cases(RUN_ID) == test_set
    assert sorted(p.name for p in (store.root / RUN_ID).iterdir()) == [
        "analysis.json",
        "manifest.json",
        "test_cases.r1.json",
    ]
    assert store.get_manifest(RUN_ID).latest_revision == 1
    assert store.next_revision(RUN_ID) == 2


def test_revisions_must_be_sequential(store: RunStore, test_set: TestCaseSet) -> None:
    store.create_run("DEMO-101")
    with pytest.raises(InvalidArtifactError, match="not the next revision"):
        store.save_test_cases(test_set.model_copy(update={"revision": 2}))


def test_revision_lookup_errors(store: RunStore, test_set: TestCaseSet) -> None:
    store.create_run("DEMO-101")
    with pytest.raises(NotFoundError, match="no submitted test cases"):
        store.load_test_cases(RUN_ID)
    store.save_test_cases(test_set)
    with pytest.raises(NotFoundError, match="no revision 5"):
        store.load_test_cases(RUN_ID, 5)


@pytest.mark.parametrize("bad", ["../../etc", "..", "20261005T120000Z-ABC123", "x/../y"])
def test_rejects_unsafe_run_ids(store: RunStore, bad: str) -> None:
    with pytest.raises(NotFoundError):
        store.get_manifest(bad)


def test_missing_run_and_artifact(store: RunStore) -> None:
    with pytest.raises(NotFoundError, match="does not exist"):
        store.get_manifest(RUN_ID)
    store.create_run("DEMO-101")
    with pytest.raises(NotFoundError, match=r"analysis\.json does not exist"):
        store.load_analysis(RUN_ID)


def test_corrupt_artifact_is_reported(store: RunStore) -> None:
    store.create_run("DEMO-101")
    (store.root / RUN_ID / "analysis.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(InvalidArtifactError, match="corrupt"):
        store.load_analysis(RUN_ID)


def test_write_bytes_refuses_paths_outside_store(store: RunStore, tmp_path: Path) -> None:
    with pytest.raises(NotFoundError, match="outside"):
        store.write_bytes(tmp_path / "evil.csv", b"x")


def test_list_runs_filters_and_sorts(tmp_path: Path) -> None:
    ids = iter(["20261005T120000Z-000001", "20261005T130000Z-000002", "20261005T140000Z-000003"])
    store = RunStore(tmp_path, clock=lambda: FIXED_NOW, id_factory=lambda _: next(ids))
    assert store.list_runs() == []
    store.create_run("DEMO-1")
    store.create_run("DEMO-2")
    store.create_run("DEMO-1")
    assert [m.run_id[-1] for m in store.list_runs()] == ["3", "2", "1"]
    assert [m.run_id[-1] for m in store.list_runs("DEMO-1")] == ["3", "1"]
