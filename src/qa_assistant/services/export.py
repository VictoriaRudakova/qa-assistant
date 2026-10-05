"""Exports a validated revision to CSV. Reads only from the run store, never from the LLM."""

from __future__ import annotations

import hashlib

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
        self, run_id: str, revision: int | None = None, *, overwrite: bool = False
    ) -> ExportResult:
        if self._exporter is None:
            raise NotConfiguredError(
                "Xray CSV mapping is not configured. Set XRAY_CSV_MAPPING_FILE."
            )
        test_set = self._store.load_test_cases(run_id, revision)
        # Re-validate rather than trusting the stored report: rules may have changed.
        report = validate_test_cases(test_set, self._store.load_analysis(run_id))
        if not report.valid:
            codes = sorted({i.code for i in report.errors})
            raise ExportBlockedError(
                f"Revision {test_set.revision} has {len(report.errors)} validation error(s) "
                f"({', '.join(codes)}). Fix them and submit a new revision."
            )

        path = self._store.export_path(run_id, test_set.revision)
        if path.exists() and not overwrite:
            raise ExportBlockedError(f"{path.name} already exists; pass overwrite=true.")

        mapping = self._exporter.mapping
        rendered = self._exporter.render(test_set)
        data = rendered.text.encode(mapping.encoding)
        self._store.write_bytes(path, data)

        warnings = [f"{w.code}: {w.message}" for w in report.warnings]
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
            warnings=warnings,
        )
