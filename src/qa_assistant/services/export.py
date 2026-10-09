"""Exports a validated revision to CSV. Reads only from the run store, never from the LLM."""

from __future__ import annotations

import hashlib

from qa_assistant.domain.enums import Readiness
from qa_assistant.domain.results import ExportResult
from qa_assistant.errors import ExportBlockedError, NotConfiguredError
from qa_assistant.storage.run_store import RunStore
from qa_assistant.testdesign.rules import validate_test_cases
from qa_assistant.xray.ports import XrayCsvExporter


class ExportService:
    def __init__(self, store: RunStore, exporter: XrayCsvExporter | None) -> None:
        self._store = store
        self._exporter = exporter

    def export_xray_csv(
        self,
        run_id: str,
        revision: int | None = None,
        *,
        overwrite: bool = False,
        ready_only: bool = False,
    ) -> ExportResult:
        """Export a revision that passes final export validation.

        By default every case must be ``ready``. With ``ready_only`` the
        ``clarification_required`` cases are left out and the remaining set is validated on
        its own (so it must still cover every acceptance criterion). Cases that need
        clarification are never written to the file.
        """
        if self._exporter is None:
            raise NotConfiguredError(
                "Xray CSV mapping is not configured. Set XRAY_CSV_MAPPING_FILE."
            )
        test_set = self._store.load_test_cases(run_id, revision)
        analysis = self._store.load_analysis(run_id)
        # Re-validate rather than trusting the stored report: rules may have changed.
        report = validate_test_cases(test_set, analysis)
        if not report.valid:
            raise _blocked(test_set.revision, sorted({i.code for i in report.errors}))

        excluded = report.clarification_required_test_case_ids
        if excluded and not ready_only:
            raise ExportBlockedError(
                f"Revision {test_set.revision} has {len(excluded)} test case(s) that need "
                f"clarification (CLARIFICATION_REQUIRED: {', '.join(excluded)}). Resolve the "
                "open questions and submit a new revision, or export with ready_only=true to "
                "leave them out."
            )
        if excluded:
            ready = [tc for tc in test_set.test_cases if tc.status is Readiness.READY]
            if not ready:
                raise ExportBlockedError(
                    f"Revision {test_set.revision} has no ready test cases to export."
                )
            test_set = test_set.model_copy(update={"test_cases": ready})
            report = validate_test_cases(test_set, analysis)
            if not report.valid:
                raise _blocked(
                    test_set.revision,
                    sorted({i.code for i in report.errors}),
                    "after leaving out cases that need clarification",
                )

        path = self._store.export_path(run_id, test_set.revision)
        if path.exists() and not overwrite:
            raise ExportBlockedError(f"{path.name} already exists; pass overwrite=true.")

        mapping = self._exporter.mapping
        rendered = self._exporter.render(test_set)
        data = rendered.text.encode(mapping.encoding)
        self._store.write_bytes(path, data)

        warnings = [f"{w.code}: {w.message}" for w in report.warnings]
        if excluded:
            warnings.insert(
                0,
                f"Left out {len(excluded)} case(s) that need clarification: {', '.join(excluded)}.",
            )
        if mapping.synthetic:
            warnings.insert(
                0, f"Mapping '{mapping.name}' is a synthetic placeholder; not for real import."
            )
        return ExportResult(
            run_id=run_id,
            revision=test_set.revision,
            path=str(path),
            mapping_name=mapping.name,
            rows=rendered.rows,
            test_case_count=len(test_set.test_cases),
            sha256=hashlib.sha256(data).hexdigest(),
            excluded_test_case_ids=excluded,
            warnings=warnings,
        )


def _blocked(revision: int, codes: list[str], context: str = "") -> ExportBlockedError:
    suffix = f" {context}" if context else ""
    return ExportBlockedError(
        f"Revision {revision} has validation error(s){suffix} ({', '.join(codes)}). "
        "Fix them and submit a new revision."
    )
