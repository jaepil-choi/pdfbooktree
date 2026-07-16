"""재현 가능한 단일 실행 directory와 manifest lifecycle을 관리한다."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Literal

import fitz

from pdfbooktree.config_io import ResolvedConfig
from pdfbooktree.utils.hashing import file_sha256
from pdfbooktree.utils.jsonio import write_json
from pdfbooktree.utils.paths import safe_filename


RUN_MANIFEST_SCHEMA_VERSION = 1
RunStatus = Literal["created", "running", "succeeded", "failed"]


class RunError(ValueError):
    """run identity나 immutable directory를 만들 수 없을 때 발생한다."""


@dataclass(frozen=True)
class InputIdentity:
    """실행 입력 PDF를 내용과 page 수로 식별한다."""

    path: Path
    sha256: str
    size_bytes: int
    page_count: int


@dataclass(frozen=True)
class ToolIdentity:
    """실행에 사용한 package와 source revision을 식별한다."""

    package_version: str
    git_revision: str | None
    git_dirty: bool | None


@dataclass(frozen=True)
class RunManifest:
    """한 번의 process 실행에 필요한 재현 정보와 상태다."""

    schema_version: int
    run_id: str
    status: RunStatus
    created_at: str
    started_at: str | None
    finished_at: str | None
    run_dir: Path
    input: InputIdentity
    tool: ToolIdentity
    config_hash: str
    resolved_config_path: Path
    config_sources: tuple[dict[str, Any], ...]
    processing_status: str | None = None
    artifact_paths: dict[str, Path] = field(default_factory=dict)
    output_paths: dict[str, Path] = field(default_factory=dict)
    report_path: Path | None = None
    warnings: tuple[str, ...] = ()
    error: dict[str, str] | None = None
    plan_source: dict[str, str] | None = None


@dataclass
class RunContext:
    """RunManifest를 created/running/final 상태로 안전하게 갱신한다."""

    manifest: RunManifest
    manifest_path: Path

    @property
    def run_dir(self) -> Path:
        return self.manifest.run_dir

    def start(self) -> RunManifest:
        """실행 시작 시각과 running 상태를 기록한다."""

        self.manifest = replace(
            self.manifest,
            status="running",
            started_at=_utc_now(),
        )
        self._write()
        return self.manifest

    def complete(self, result: object) -> RunManifest:
        """ProcessingResult의 경로와 상태로 manifest를 완료한다."""

        processing_status = str(getattr(result, "status", "unknown"))
        status: RunStatus = "failed" if processing_status == "failed" else "succeeded"
        artifacts = dict(getattr(result, "artifact_paths", {}) or {})
        outputs: dict[str, Path] = {}
        for name in ("output_pdf", "output_markdown_dir", "ocr_pdf"):
            value = getattr(result, name, None)
            if isinstance(value, Path) and value.exists():
                outputs[name] = value
        report_path = getattr(result, "report_path", None)
        report = report_path if isinstance(report_path, Path) else None
        warnings = tuple(str(item) for item in getattr(result, "warnings", ()) or ())
        self.manifest = replace(
            self.manifest,
            status=status,
            finished_at=_utc_now(),
            processing_status=processing_status,
            artifact_paths=artifacts,
            output_paths=outputs,
            report_path=report,
            warnings=warnings,
        )
        self._write()
        return self.manifest

    def record_plan_source(self, path: Path, sha256: str) -> RunManifest:
        """명시적 ``apply``가 사용한 plan 파일의 경로와 SHA-256을 기록한다."""

        self.manifest = replace(
            self.manifest,
            plan_source={"path": str(path), "sha256": sha256},
        )
        self._write()
        return self.manifest

    def fail(self, error: Exception) -> RunManifest:
        """예외 정보를 최소 형태로 기록하고 failed 상태로 끝낸다."""

        self.manifest = replace(
            self.manifest,
            status="failed",
            finished_at=_utc_now(),
            error={
                "type": type(error).__name__,
                "message": str(error),
            },
        )
        self._write()
        return self.manifest

    def _write(self) -> None:
        write_json(self.manifest_path, self.manifest)


def create_run_context(
    input_pdf: Path | str,
    output_root: Path | str,
    resolved: ResolvedConfig,
    *,
    run_dir: Path | str | None = None,
    repository_root: Path | str | None = None,
) -> RunContext:
    """입력/config hash로 충돌하지 않는 immutable run directory를 만든다."""

    input_path = Path(input_pdf).resolve()
    if not input_path.is_file():
        raise RunError(f"입력 PDF가 없다: {input_path}")
    try:
        with fitz.open(input_path) as document:
            page_count = document.page_count
    except (fitz.FileDataError, RuntimeError) as error:
        raise RunError(
            f"입력 PDF를 열지 못했다: {input_path}, reason={error}"
        ) from error

    input_hash = file_sha256(input_path)
    identity = InputIdentity(
        path=input_path,
        sha256=input_hash,
        size_bytes=input_path.stat().st_size,
        page_count=page_count,
    )
    run_id = _run_id(input_hash, resolved.config_hash)
    if run_dir is None:
        book_id = f"{safe_filename(input_path.stem, max_length=60)}-{input_hash[:8]}"
        target = Path(output_root).resolve() / book_id / run_id
    else:
        target = Path(run_dir).resolve()
    try:
        target.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise RunError(f"run directory가 이미 있다: {target}") from error

    resolved_path = target / "config.resolved.json"
    write_json(resolved_path, resolved.data)
    manifest_path = target / "run_manifest.json"
    manifest = RunManifest(
        schema_version=RUN_MANIFEST_SCHEMA_VERSION,
        run_id=run_id,
        status="created",
        created_at=_utc_now(),
        started_at=None,
        finished_at=None,
        run_dir=target,
        input=identity,
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
    return RunContext(manifest=manifest, manifest_path=manifest_path)


def tool_identity(repository_root: Path | None = None) -> ToolIdentity:
    """설치 package version과 가능한 경우 git revision/dirty 상태를 읽는다."""

    try:
        package_version = metadata.version("pdfbooktree")
    except metadata.PackageNotFoundError:
        package_version = "0+unknown"
    revision = _git_output(repository_root, "rev-parse", "HEAD")
    dirty_output = _git_output(repository_root, "status", "--porcelain")
    return ToolIdentity(
        package_version=package_version,
        git_revision=revision or None,
        git_dirty=bool(dirty_output) if dirty_output is not None else None,
    )


def _git_output(repository_root: Path | None, *args: str) -> str | None:
    if repository_root is None:
        return None
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _run_id(input_hash: str, config_hash: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{input_hash[:8]}-{config_hash[:8]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
