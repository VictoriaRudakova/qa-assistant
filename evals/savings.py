"""Measure what ``keep_ids`` saves when test cases are resubmitted.

Every stored revision after the first is replayed through the real ``submit_test_cases``
in a temporary store: cases whose content is identical to a case of the previous revision
are sent as ``keep_ids``, the rest as new cases. The replay is *equivalent* when each
replayed revision holds the same case contents and gets the same validation outcome
(validity, export readiness, issue codes, readiness counts) as the recorded one.

Sizes are the JSON bytes of the tool request, not tokens. The stored runs are only read.
"""

from __future__ import annotations

import json
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from qa_assistant.domain.test_case import TestCase, TestCaseDraft
from qa_assistant.domain.validation import ValidationReport
from qa_assistant.errors import InvalidArtifactError
from qa_assistant.services.runs import RunService
from qa_assistant.storage.run_store import RunStore


@dataclass(frozen=True)
class Savings:
    run_id: str
    revisions: int
    full_bytes: int  # resubmissions (revision 2 onward) sent in full
    delta_bytes: int  # the same resubmissions with keep_ids
    equivalent: bool


def replay(store_dir: Path, run_id: str) -> Savings:
    recorded = RunStore(store_dir)
    manifest = recorded.get_manifest(run_id)
    full = delta = 0
    equivalent = True
    with tempfile.TemporaryDirectory() as tmp:
        store = RunStore(Path(tmp), id_factory=lambda _: run_id)
        store.create_run(manifest.story_key)
        store.save_analysis(run_id, recorded.load_analysis(run_id))
        service = RunService(store)
        previous: list[TestCase] = []
        for revision in range(1, (manifest.latest_revision or 0) + 1):
            cases = recorded.load_test_cases(run_id, revision).test_cases
            drafts = [_draft(tc) for tc in cases]
            if revision == 1:
                report = service.submit_test_cases(run_id, drafts).report
            else:
                keep, changed = _split(previous, cases)
                full += _request_bytes(run_id, drafts)
                try:
                    report = service.submit_test_cases(
                        run_id, changed, keep_ids=keep, keep_from_revision=revision - 1
                    ).report
                    delta += _request_bytes(run_id, changed, keep, revision - 1)
                except InvalidArtifactError:  # e.g. a re-sent case titled like a kept one
                    report = service.submit_test_cases(run_id, drafts).report
                    delta += _request_bytes(run_id, drafts)
            replayed = store.load_test_cases(run_id, revision).test_cases
            expected = RunService(recorded).validate_test_cases(run_id, revision)
            equivalent &= sorted(map(_body, replayed)) == sorted(map(_body, cases))
            equivalent &= _outcome(report) == _outcome(expected)
            previous = replayed
    return Savings(run_id, manifest.latest_revision or 0, full, delta, equivalent)


def savings_table(stores: Sequence[tuple[str, Path]]) -> tuple[list[str], bool]:
    """One row per run with resubmissions, and whether every replay was equivalent.
    ``stores`` are (label, run store dir) pairs."""
    rows = [f"{'run':72} {'revs':>4} {'full_B':>8} {'keep_B':>8} {'saved':>6}  equivalent"]
    total_full = total_delta = replayed = skipped = 0
    ok = True
    for name, store_dir in stores:
        for manifest in RunStore(store_dir).list_runs():
            if (manifest.latest_revision or 0) < 2:
                continue
            label = f"{name}/{manifest.run_id}" if name else manifest.run_id
            try:
                s = replay(store_dir, manifest.run_id)
            except InvalidArtifactError:  # never counted in the totals
                skipped += 1
                rows.append(f"{label[-72:]:72} skipped (legacy): artifacts predate the schema")
                continue
            replayed += 1
            total_full, total_delta = total_full + s.full_bytes, total_delta + s.delta_bytes
            ok &= s.equivalent
            rows.append(
                f"{label[-72:]:72} {s.revisions:>4} {s.full_bytes:>8} {s.delta_bytes:>8} "
                f"{_saved(s.full_bytes, s.delta_bytes):>6}  {s.equivalent}"
            )
    rows.append(
        f"{f'total of {replayed} replayed runs ({skipped} legacy skipped)':72} {'':>4} "
        f"{total_full:>8} {total_delta:>8} {_saved(total_full, total_delta):>6}  "
        "(resubmission request JSON bytes of replayed runs only, not tokens)"
    )
    return rows, ok


def _split(
    previous: list[TestCase], cases: list[TestCase]
) -> tuple[list[str], list[TestCaseDraft]]:
    """Each case identical to a not yet kept previous case is kept; the rest is re-sent."""
    pool: dict[str, list[str]] = {}
    for tc in previous:
        pool.setdefault(_body(tc), []).append(tc.id)
    keep: list[str] = []
    changed: list[TestCaseDraft] = []
    for tc in cases:
        ids = pool.get(_body(tc))
        if ids:
            keep.append(ids.pop(0))
        else:
            changed.append(_draft(tc))
    return keep, changed


def _draft(tc: TestCase) -> TestCaseDraft:
    return TestCaseDraft(**tc.model_dump(exclude={"id"}))


def _body(tc: TestCase) -> str:
    return json.dumps(tc.model_dump(mode="json", exclude={"id"}), sort_keys=True)


def _request_bytes(
    run_id: str,
    drafts: list[TestCaseDraft],
    keep: list[str] | None = None,
    base: int | None = None,
) -> int:
    request: dict[str, object] = {
        "run_id": run_id,
        "test_cases": [d.model_dump(mode="json") for d in drafts],
    }
    if keep:
        request |= {"keep_ids": keep, "keep_from_revision": base}
    return len(json.dumps(request))


def _outcome(report: ValidationReport) -> tuple[object, ...]:
    return (
        report.valid,
        report.export_ready,
        Counter((i.code, i.severity) for i in report.issues),
        len(report.ready_test_case_ids),
        len(report.clarification_required_test_case_ids),
    )


def _saved(full: int, delta: int) -> str:
    return f"{1 - delta / full:.1%}" if full else "-"
