"""File-based run store.

Layout::

    <output_dir>/runs/<run_id>/
        manifest.json
        analysis.json
        test_cases.r<N>.json      # one file per submitted revision
        export.r<N>.csv

Validation reports are not stored: they are cheap to recompute, and export always
re-validates, so a stored copy could only go stale.

Every artifact is written atomically. Run ids are validated against a strict pattern and
paths are checked to stay inside the store, so tool input can never escape ``output/``.
"""

from __future__ import annotations

import os
import re
import secrets
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from qa_assistant.domain.analysis import StoryAnalysis
from qa_assistant.domain.results import RunManifest
from qa_assistant.domain.test_case import TestCaseSet
from qa_assistant.errors import InvalidArtifactError, NotFoundError

RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{6}$")

ModelT = TypeVar("ModelT", bound=BaseModel)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def new_run_id(now: datetime) -> str:
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"


class RunStore:
    def __init__(
        self,
        output_dir: Path,
        *,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[datetime], str] = new_run_id,
    ) -> None:
        self._root = (output_dir / "runs").resolve()
        self._clock = clock
        self._id_factory = id_factory

    @property
    def root(self) -> Path:
        return self._root

    def now(self) -> datetime:
        return self._clock()

    # ---------------------------------------------------------------- runs
    def create_run(self, story_key: str) -> RunManifest:
        created_at = self._clock()
        manifest = RunManifest(
            run_id=self._id_factory(created_at), story_key=story_key, created_at=created_at
        )
        run_dir = self._run_dir(manifest.run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        self._write_model(run_dir / "manifest.json", manifest)
        return manifest

    def get_manifest(self, run_id: str) -> RunManifest:
        return self._read_model(self._existing_run_dir(run_id) / "manifest.json", RunManifest)

    def list_runs(self, story_key: str | None = None) -> list[RunManifest]:
        if not self._root.is_dir():
            return []
        manifests = [
            self.get_manifest(path.name)
            for path in self._root.iterdir()
            if path.is_dir() and RUN_ID_RE.match(path.name)
        ]
        if story_key is not None:
            manifests = [m for m in manifests if m.story_key == story_key]
        return sorted(manifests, key=lambda m: m.run_id, reverse=True)

    # ---------------------------------------------------------------- artifacts
    def save_analysis(self, run_id: str, analysis: StoryAnalysis) -> Path:
        path = self._existing_run_dir(run_id) / "analysis.json"
        self._write_model(path, analysis)
        return path

    def load_analysis(self, run_id: str) -> StoryAnalysis:
        return self._read_model(self._existing_run_dir(run_id) / "analysis.json", StoryAnalysis)

    def next_revision(self, run_id: str) -> int:
        return (self.get_manifest(run_id).latest_revision or 0) + 1

    def save_test_cases(self, test_set: TestCaseSet) -> None:
        run_dir = self._existing_run_dir(test_set.run_id)
        manifest = self.get_manifest(test_set.run_id)
        if test_set.revision != (manifest.latest_revision or 0) + 1:
            raise InvalidArtifactError(
                f"Revision {test_set.revision} is not the next revision of run {test_set.run_id}."
            )
        self._write_model(run_dir / f"test_cases.r{test_set.revision}.json", test_set)
        manifest.latest_revision = test_set.revision
        self._write_model(run_dir / "manifest.json", manifest)

    def load_test_cases(self, run_id: str, revision: int | None = None) -> TestCaseSet:
        revision = self._resolve_revision(run_id, revision)
        path = self._existing_run_dir(run_id) / f"test_cases.r{revision}.json"
        return self._read_model(path, TestCaseSet)

    def export_path(self, run_id: str, revision: int) -> Path:
        return self._existing_run_dir(run_id) / f"export.r{revision}.csv"

    def write_bytes(self, path: Path, data: bytes) -> None:
        self._ensure_inside(path)
        self._atomic_write(path, data)

    # ---------------------------------------------------------------- internals
    def _resolve_revision(self, run_id: str, revision: int | None) -> int:
        latest = self.get_manifest(run_id).latest_revision
        if latest is None:
            raise NotFoundError(f"Run {run_id} has no submitted test cases.")
        if revision is None:
            return latest
        if not 1 <= revision <= latest:
            raise NotFoundError(f"Run {run_id} has no revision {revision} (latest: {latest}).")
        return revision

    def _run_dir(self, run_id: str) -> Path:
        if not RUN_ID_RE.match(run_id):
            raise NotFoundError(f"Invalid run id: {run_id!r}.")
        path = self._root / run_id
        self._ensure_inside(path)
        return path

    def _existing_run_dir(self, run_id: str) -> Path:
        path = self._run_dir(run_id)
        if not path.is_dir():
            raise NotFoundError(f"Run {run_id} does not exist.")
        return path

    def _ensure_inside(self, path: Path) -> None:
        if not path.resolve().is_relative_to(self._root):
            raise NotFoundError("Path is outside the run store.")

    def _write_model(self, path: Path, model: BaseModel) -> None:
        self._atomic_write(path, (model.model_dump_json(indent=2) + "\n").encode("utf-8"))

    @staticmethod
    def _read_model(path: Path, model_type: type[ModelT]) -> ModelT:
        try:
            return model_type.model_validate_json(path.read_bytes())
        except FileNotFoundError as exc:
            raise NotFoundError(f"Artifact {path.name} does not exist.") from exc
        except ValidationError as exc:
            raise InvalidArtifactError(f"Stored artifact {path.name} is corrupt: {exc}") from exc

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            Path(tmp_name).replace(path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
