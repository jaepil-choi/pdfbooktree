"""재현 가능한 batch 실행 directory와 manifest lifecycle을 관리한다."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pdfbooktree.config_io import ResolvedConfig
from pdfbooktree.models import BatchItemResult, BatchResult
from pdfbooktree.run import ToolIdentity, tool_identity
from pdfbooktree.utils.hashing import stable_json_hash
from pdfbooktree.utils.jsonio import write_json


BATCH_RUN_MANIFEST_SCHEMA_VERSION = 1
BatchRunStatus = Literal["created", "running", "succeeded", "failed"]


class BatchRunError(ValueError):
    """batch run identity나 immutable directory를 만들 수 없을 때 발생한다."""


@dataclass(frozen=True)
class BatchItemRunReference:
    """batch manifest가 가리키는 단일 item run과 실제 output이다."""

    input_pdf: Path
    status: str
    run_id: str | None
    manifest_path: Path | None
    output_paths: dict[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class BatchRunSummary:
    """완료되거나 중단된 batch의 처리 집계다."""

    total_pdf_count: int
    completed_count: int
    processed_count: int
    skipped_existing_bookmark_count: int
    failed_count: int
    bookmark_reference_candidate_count: int


@dataclass(frozen=True)
class BatchRunManifest:
    """한 번의 batch 실행에 필요한 재현 정보와 item run 연결이다."""

    schema_version: int
    batch_run_id: str
    status: BatchRunStatus
    created_at: str
    started_at: str | None
    finished_at: str | None
    batch_run_dir: Path
    input_dir: Path
    output_root: Path
    recursive: bool
    discovered_pdf_count: int
    discovered_pdf_paths: tuple[Path, ...]
    selection_hash: str
    tool: ToolIdentity
    config_hash: str
    resolved_config_path: Path
    config_sources: tuple[dict[str, Any], ...]
    summary: BatchRunSummary | None = None
    item_runs: tuple[BatchItemRunReference, ...] = ()
    error: dict[str, str] | None = None


@dataclass
class BatchRunContext:
    """BatchRunManifest를 created/running/final 상태로 갱신한다."""

    manifest: BatchRunManifest
    manifest_path: Path

    @property
    def batch_run_dir(self) -> Path:
        return self.manifest.batch_run_dir

    def start(self) -> BatchRunManifest:
        """batch 시작 시각과 running 상태를 기록한다."""

        self.manifest = replace(
            self.manifest,
            status="running",
            started_at=_utc_now(),
        )
        self._write()
        return self.manifest

    def complete(self, result: BatchResult) -> BatchRunManifest:
        """부분 item 실패를 포함한 정상 종료를 succeeded로 기록한다."""

        self.manifest = replace(
            self.manifest,
            status="succeeded",
            finished_at=_utc_now(),
            summary=_summary(result),
            item_runs=_item_run_references(result.results),
        )
        self._write()
        return self.manifest

    def fail(
        self, error: Exception, result: BatchResult | None = None
    ) -> BatchRunManifest:
        """command 전체를 중단시킨 예외와 완료된 item run을 기록한다."""

        self.manifest = replace(
            self.manifest,
            status="failed",
            finished_at=_utc_now(),
            summary=_summary(result) if result is not None else None,
            item_runs=(
                _item_run_references(result.results) if result is not None else ()
            ),
            error={
                "type": type(error).__name__,
                "message": str(error),
            },
        )
        self._write()
        return self.manifest

    def _write(self) -> None:
        write_json(self.manifest_path, self.manifest)


def create_batch_run_context(
    input_dir: Path | str,
    output_root: Path | str,
    resolved: ResolvedConfig,
    *,
    recursive: bool,
    pdf_paths: list[Path],
    repository_root: Path | str | None = None,
) -> BatchRunContext:
    """입력 선택/config로 충돌하지 않는 immutable batch run을 만든다."""

    input_path = Path(input_dir).resolve()
    if not input_path.is_dir():
        raise BatchRunError(f"입력 디렉터리가 없다: {input_path}")
    output_path = Path(output_root).resolve()
    discovered_paths = tuple(path.resolve() for path in pdf_paths)
    selection_hash = stable_json_hash(
        {
            "input_dir": input_path,
            "recursive": recursive,
            "discovered_pdf_paths": discovered_paths,
        }
    )
    batch_run_id = _batch_run_id(selection_hash, resolved.config_hash)
    target = output_path / "_batch_runs" / batch_run_id
    try:
        target.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise BatchRunError(f"batch run directory가 이미 있다: {target}") from error

    resolved_path = target / "config.resolved.json"
    write_json(resolved_path, resolved.data)
    manifest_path = target / "batch_manifest.json"
    manifest = BatchRunManifest(
        schema_version=BATCH_RUN_MANIFEST_SCHEMA_VERSION,
        batch_run_id=batch_run_id,
        status="created",
        created_at=_utc_now(),
        started_at=None,
        finished_at=None,
        batch_run_dir=target,
        input_dir=input_path,
        output_root=output_path,
        recursive=recursive,
        discovered_pdf_count=len(discovered_paths),
        discovered_pdf_paths=discovered_paths,
        selection_hash=selection_hash,
        tool=tool_identity(
            Path(repository_root).resolve()
            if repository_root is not None
            else Path.cwd()
        ),
        config_hash=resolved.config_hash,
        resolved_config_path=resolved_path,
        config_sources=resolved.sources,
    )
    write_json(manifest_path, manifest)
    return BatchRunContext(manifest=manifest, manifest_path=manifest_path)


def _summary(result: BatchResult) -> BatchRunSummary:
    return BatchRunSummary(
        total_pdf_count=result.total_pdf_count,
        completed_count=len(result.results),
        processed_count=result.processed_count,
        skipped_existing_bookmark_count=result.skipped_existing_bookmark_count,
        failed_count=result.failed_count,
        bookmark_reference_candidate_count=result.bookmark_reference_candidate_count,
    )


def _item_run_references(
    results: list[BatchItemResult],
) -> tuple[BatchItemRunReference, ...]:
    return tuple(
        BatchItemRunReference(
            input_pdf=result.input_pdf,
            status=result.status,
            run_id=result.run_id,
            manifest_path=result.manifest_path,
            output_paths=_existing_output_paths(result),
        )
        for result in results
    )


def _existing_output_paths(result: BatchItemResult) -> dict[str, Path]:
    outputs: dict[str, Path] = {}
    for name in ("output_pdf", "output_markdown_dir", "ocr_pdf"):
        value = getattr(result, name)
        if isinstance(value, Path) and value.exists():
            outputs[name] = value
    return outputs


def _batch_run_id(selection_hash: str, config_hash: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{selection_hash[:8]}-{config_hash[:8]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
