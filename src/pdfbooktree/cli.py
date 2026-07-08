"""Typer 기반 CLI entrypoint다."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import typer
from rich import print as rich_print

from pdfbooktree.batch import BatchProcessor
from pdfbooktree.classify import (
    ClassifyBatchConfig,
    ClassifyLogMode,
    ScanBookmarkClassifier,
    build_classify_logger,
    default_classify_log_mode,
)
from pdfbooktree.config import ProcessingConfig, TypographyConfig
from pdfbooktree.ocr import (
    OcrOverlayBatchConfig,
    OcrOverlayBatchRunner,
    OcrOverlayBuilder,
    OcrOverlayConfig,
)
from pdfbooktree.ocr.logger import OcrLogMode, build_ocr_logger, default_ocr_log_mode
from pdfbooktree.pdf.scan_signals import DEFAULT_MAX_SAMPLE_PAGES
from pdfbooktree.processor import Processor
from pdfbooktree.utils.jsonio import to_jsonable

app = typer.Typer(
    help="PDF 책의 typography hierarchy로 bookmark와 Markdown tree를 만든다."
)


def parse_page_ranges(value: str | None) -> list[int] | None:
    """CLI의 1-3,42 형태 page range 문자열을 1-based page 목록으로 바꾼다."""

    if value is None or not value.strip():
        return None
    pages: list[int] = []
    for part in value.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start > end:
                raise typer.BadParameter(f"page range 시작이 끝보다 크다: {token}")
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(token))
    if any(page < 1 for page in pages):
        raise typer.BadParameter("PDF page는 1 이상이어야 한다.")
    return sorted(dict.fromkeys(pages))


def parse_engine_options(values: list[str]) -> dict[str, object]:
    """--engine-option key=value 목록을 dict로 변환한다."""

    options: dict[str, object] = {}
    for value in values:
        if "=" not in value:
            raise typer.BadParameter("--engine-option은 key=value 형식이어야 한다.")
        key, raw = value.split("=", 1)
        key = key.strip()
        if not key:
            raise typer.BadParameter("--engine-option key가 비어 있다.")
        options[key] = _coerce_engine_option_value(raw.strip())
    return options


def _coerce_engine_option_value(value: str) -> object:
    if "," in value:
        return [
            _coerce_engine_option_value(part.strip())
            for part in value.split(",")
            if part.strip()
        ]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


@app.command()
def ocr_overlay(
    pdf: Path = typer.Argument(..., help="OCR overlay를 만들 PDF 파일이다."),
    output_pdf: Path = typer.Option(
        ..., "--output", "-o", help="생성할 searchable OCR PDF 경로다."
    ),
    output_dir: Path = typer.Option(
        ..., "--output-dir", help="OCR cache와 stats artifact를 저장할 디렉터리다."
    ),
    engine: str = typer.Option("upstage", "--engine", help="OCR engine 이름이다."),
    render_dpi: int = typer.Option(300, "--render-dpi", min=72, help="렌더링 DPI다."),
    pages: str | None = typer.Option(
        None, "--pages", help="처리할 1-based page 목록이다. 예: 1-3,42"
    ),
    force: bool = typer.Option(
        False, "--force", help="출력 PDF가 이미 있어도 덮어쓴다."
    ),
    confirm_bookmark_ocr_overwrite: bool = typer.Option(
        False,
        "--confirm-bookmark-ocr-overwrite",
        help="기존 bookmark가 있는 PDF의 OCR text layer 교체를 명시적으로 확인한다.",
    ),
    stats_word_level: bool = typer.Option(
        False, "--stats-word-level", help="word 단위 stats artifact도 저장한다."
    ),
    engine_option: list[str] = typer.Option(
        [],
        "--engine-option",
        help="OCR engine option이다. key=value 형식이며 여러 번 줄 수 있다.",
    ),
    log_mode: str = typer.Option(
        "auto",
        "--log-mode",
        help="OCR runtime 로그 출력 방식이다. auto, rich, plain, json, none 중 하나다.",
    ),
    no_log_file: bool = typer.Option(
        False,
        "--no-log-file",
        help="ocr_log.jsonl과 ocr_progress.json 파일 기록을 끈다.",
    ),
) -> None:
    """PDF 모든 page를 OCR parse한 뒤 invisible text layer를 다시 입힌다."""

    resolved_log_mode = default_ocr_log_mode() if log_mode == "auto" else log_mode
    if resolved_log_mode not in {"rich", "plain", "json", "none"}:
        raise typer.BadParameter(
            "log-mode은 auto, rich, plain, json, none 중 하나여야 한다."
        )
    logger = build_ocr_logger(
        cast(OcrLogMode, resolved_log_mode), output_dir, enable_file=not no_log_file
    )
    config = OcrOverlayConfig(
        input_pdf=pdf,
        output_pdf=output_pdf,
        output_dir=output_dir,
        engine=engine,
        engine_options=parse_engine_options(engine_option),
        render_dpi=render_dpi,
        pages=parse_page_ranges(pages),
        force=force,
        confirm_bookmark_ocr_overwrite=confirm_bookmark_ocr_overwrite,
        stats_word_level=stats_word_level,
    )
    result = OcrOverlayBuilder(config, logger=logger).run()
    rich_print(to_jsonable(result))


@app.command("ocr-overlay-batch")
def ocr_overlay_batch_cmd(
    input_dir: Path = typer.Argument(..., help="PDF를 찾을 입력 디렉터리다."),
    output_dir: Path = typer.Option(
        ..., "--output-dir", "-o", help="OCR batch 산출물을 저장할 디렉터리다."
    ),
    recursive: bool = typer.Option(
        False, "--recursive", "-r", help="하위 디렉터리까지 찾는다."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="target 판정과 report만 만들고 OCR API 호출과 PDF 생성을 하지 않는다.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="출력 PDF가 이미 있어도 덮어쓴다. 기본값은 기존 output을 skip한다.",
    ),
    confirm_bookmark_ocr_overwrite: bool = typer.Option(
        False,
        "--confirm-bookmark-ocr-overwrite",
        help="기존 bookmark가 있는 target PDF의 OCR text layer 교체를 명시적으로 확인한다.",
    ),
    engine: str = typer.Option("upstage", "--engine", help="OCR engine 이름이다."),
    render_dpi: int = typer.Option(300, "--render-dpi", min=72, help="렌더링 DPI다."),
    max_sample_pages: int = typer.Option(
        DEFAULT_MAX_SAMPLE_PAGES,
        "--max-sample-pages",
        min=1,
        help="target 판정을 위해 문서당 sampling할 최대 page 수다.",
    ),
    stats_word_level: bool = typer.Option(
        False, "--stats-word-level", help="word 단위 stats artifact도 저장한다."
    ),
    engine_option: list[str] = typer.Option(
        [],
        "--engine-option",
        help="OCR engine option이다. key=value 형식이며 여러 번 줄 수 있다.",
    ),
    log_mode: str = typer.Option(
        "auto",
        "--log-mode",
        help="파일별 OCR runtime 로그 출력 방식이다. auto, rich, plain, json, none 중 하나다.",
    ),
    no_log_file: bool = typer.Option(
        False,
        "--no-log-file",
        help="파일별 ocr_log.jsonl과 ocr_progress.json 기록을 끈다.",
    ),
) -> None:
    """디렉터리 안 target PDF만 골라 OCR overlay를 batch 실행한다."""

    resolved_log_mode = default_ocr_log_mode() if log_mode == "auto" else log_mode
    if resolved_log_mode not in {"rich", "plain", "json", "none"}:
        raise typer.BadParameter(
            "log-mode은 auto, rich, plain, json, none 중 하나여야 한다."
        )
    config = OcrOverlayBatchConfig(
        input_dir=input_dir,
        output_dir=output_dir,
        recursive=recursive,
        dry_run=dry_run,
        force=force,
        confirm_bookmark_ocr_overwrite=confirm_bookmark_ocr_overwrite,
        engine=engine,
        engine_options=parse_engine_options(engine_option),
        render_dpi=render_dpi,
        max_sample_pages=max_sample_pages,
        stats_word_level=stats_word_level,
    )
    runner = OcrOverlayBatchRunner(
        config,
        ocr_logger_factory=lambda path: build_ocr_logger(
            cast(OcrLogMode, resolved_log_mode), path, enable_file=not no_log_file
        ),
    )
    result = runner.run()
    rich_print(
        to_jsonable(
            {
                "total_pdf_count": result.total_pdf_count,
                "target_count": result.target_count,
                "processed_count": result.processed_count,
                "dry_run_count": result.dry_run_count,
                "skipped_count": result.skipped_count,
                "failed_count": result.failed_count,
                "elapsed_sec": result.elapsed_sec,
                "report_csv_path": result.report_csv_path,
                "detail_jsonl_path": result.detail_jsonl_path,
                "summary_path": result.summary_path,
            }
        )
    )


@app.command()
def process(
    pdf: Path = typer.Argument(..., help="처리할 PDF 파일이다."),
    output_dir: Path = typer.Option(
        Path("."), "--output-dir", "-o", help="출력 디렉터리다."
    ),
    skip_existing_bookmarks: bool = typer.Option(
        True,
        "--skip-existing-bookmarks/--no-skip-existing-bookmarks",
        help="기존 outline이 있으면 typography 추론 대신 Markdown export만 수행한다.",
    ),
    min_tier_count: int = typer.Option(
        5,
        "--min-tier-count",
        min=1,
        help="희소 typography tier를 병합하기 위한 최소 line 수다.",
    ),
    max_heading_tier: int = typer.Option(
        3, "--max-heading-tier", min=1, help="heading 후보로 볼 최대 tier 번호다."
    ),
) -> None:
    """단일 PDF를 typography hierarchy 기반으로 처리한다."""

    config = ProcessingConfig(
        skip_existing_bookmarks=skip_existing_bookmarks,
        typography=TypographyConfig(
            min_tier_count=min_tier_count, max_heading_tier=max_heading_tier
        ),
    )
    result = Processor(pdf, output_dir, config).run()
    rich_print(to_jsonable(result))


@app.command()
def batch(
    input_dir: Path = typer.Argument(..., help="PDF를 찾을 입력 디렉터리다."),
    output_dir: Path = typer.Option(
        Path("."), "--output-dir", "-o", help="출력 디렉터리다."
    ),
    recursive: bool = typer.Option(
        False, "--recursive", "-r", help="하위 디렉터리까지 찾는다."
    ),
) -> None:
    """디렉터리 안의 PDF들을 batch 처리한다."""

    result = BatchProcessor(input_dir, output_dir, recursive=recursive).run()
    rich_print(to_jsonable(result))


@app.command("classify-scan")
def classify_scan_cmd(
    input_dir: Path = typer.Argument(..., help="PDF를 찾을 입력 디렉터리다."),
    output_dir: Path = typer.Option(
        Path("."), "--output-dir", "-o", help="분류 report를 저장할 디렉터리다."
    ),
    recursive: bool = typer.Option(
        False, "--recursive", "-r", help="하위 디렉터리까지 찾는다."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="후속 변경 작업 없이 scan/bookmark 분류만 실행한다.",
    ),
    write_report: bool = typer.Option(
        True,
        "--write-report/--no-write-report",
        help="분류 CSV/JSONL/summary report를 저장할지 정한다.",
    ),
    max_sample_pages: int = typer.Option(
        DEFAULT_MAX_SAMPLE_PAGES,
        "--max-sample-pages",
        min=1,
        help="문서당 sampling할 최대 page 수다.",
    ),
    log_mode: str = typer.Option(
        "auto",
        "--log-mode",
        help="classify 진행 로그 출력 방식이다. auto, rich, plain, json, none 중 하나다.",
    ),
) -> None:
    """디렉터리 안 PDF를 scan 여부와 bookmark 유무로 분류해 report를 만든다."""

    resolved_log_mode = default_classify_log_mode() if log_mode == "auto" else log_mode
    if resolved_log_mode not in {"rich", "plain", "json", "none"}:
        raise typer.BadParameter(
            "log-mode은 auto, rich, plain, json, none 중 하나여야 한다."
        )
    logger = build_classify_logger(cast(ClassifyLogMode, resolved_log_mode))
    config = ClassifyBatchConfig(
        input_dir=input_dir,
        output_dir=output_dir,
        recursive=recursive,
        dry_run=dry_run,
        write_report=write_report,
        max_sample_pages=max_sample_pages,
    )
    result = ScanBookmarkClassifier(config, logger=logger).run()
    rich_print(
        to_jsonable(
            {
                "total_pdf_count": result.total_pdf_count,
                "scanned_count": result.scanned_count,
                "native_count": result.native_count,
                "target_count": result.target_count,
                "error_count": result.error_count,
                "elapsed_sec": result.elapsed_sec,
                "dry_run": dry_run,
                "write_report": write_report,
                "report_csv_path": result.report_csv_path,
                "detail_jsonl_path": result.detail_jsonl_path,
            }
        )
    )


def main() -> None:
    """콘솔 script entrypoint다."""

    app()
