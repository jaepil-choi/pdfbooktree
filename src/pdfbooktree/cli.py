"""Typer 기반 CLI entrypoint다."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import typer
from rich import print as rich_print

from pdfbooktree.batch import BatchProcessor
from pdfbooktree.config import ProcessingConfig, TocMlDetectionConfig
from pdfbooktree.ocr import OcrOverlayBuilder, OcrOverlayConfig
from pdfbooktree.ocr.logger import OcrLogMode, build_ocr_logger, default_ocr_log_mode
from pdfbooktree.processor import Processor
from pdfbooktree.toc.bookmark_batch import (
    BookmarkTocBatchDetector,
    write_toc_page_dataset_csv,
)
from pdfbooktree.toc.dataset_training import (
    TocPageDatasetModelType,
    TocPageDatasetTrainer,
)
from pdfbooktree.utils.jsonio import to_jsonable
from pdfbooktree.utils.jsonio import write_json


app = typer.Typer(help="PDF 책의 TOC를 bookmark와 Markdown tree로 구조화한다.")

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
        ...,
        "--output",
        "-o",
        help="생성할 searchable OCR PDF 경로다.",
    ),
    output_dir: Path = typer.Option(
        ...,
        "--output-dir",
        help="OCR cache와 stats artifact를 저장할 디렉터리다.",
    ),
    engine: str = typer.Option("upstage", "--engine", help="OCR engine 이름이다."),
    render_dpi: int = typer.Option(300, "--render-dpi", min=72, help="렌더링 DPI다."),
    pages: str | None = typer.Option(
        None,
        "--pages",
        help="처리할 1-based page 목록이다. 예: 1-3,42",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="출력 PDF가 이미 있어도 덮어쓴다.",
    ),
    confirm_bookmark_ocr_overwrite: bool = typer.Option(
        False,
        "--confirm-bookmark-ocr-overwrite",
        help="기존 bookmark가 있는 PDF의 OCR text layer 교체를 명시적으로 확인한다.",
    ),
    stats_word_level: bool = typer.Option(
        False,
        "--stats-word-level",
        help="word 단위 stats artifact도 저장한다.",
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
        raise typer.BadParameter("log-mode은 auto, rich, plain, json, none 중 하나여야 한다.")
    logger = build_ocr_logger(
        cast(OcrLogMode, resolved_log_mode),
        output_dir,
        enable_file=not no_log_file,
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


@app.command()
def process(
    pdf: Path = typer.Argument(..., help="처리할 PDF 파일이다."),
    output_dir: Path = typer.Option(
        Path("."), "--output-dir", "-o", help="출력 디렉터리다."
    ),
    use_llm: bool = typer.Option(
        False,
        "--use-llm",
        help="런타임에서 LLM range review와 clustered item extraction을 실제 호출할지 여부다.",
    ),
    skip_existing_bookmarks: bool = typer.Option(
        True,
        "--skip-existing-bookmarks/--no-skip-existing-bookmarks",
        help=(
            "기존 bookmark가 있으면 그 트리에서 markdown을 export하고 "
            "bookmark embedding(PDF outline overwrite)만 건너뛴다. "
            "--no-skip-existing-bookmarks를 주면 기존 bookmark를 무시하고 "
            "TOC 탐지부터 강제 재처리한다."
        ),
    ),
    toc_model_path: Path = typer.Option(
        Path("outputs/300study_toc_page_dataset_model/toc_page_dataset_model.joblib"),
        "--toc-model-path",
        help="학습된 TOC page classifier joblib 파일이다. 없으면 처리 실패한다.",
    ),
    toc_probability_threshold: float = typer.Option(
        0.5,
        "--toc-probability-threshold",
        min=0.0,
        max=1.0,
        help="TOC page classifier positive 판정 확률 임계값이다.",
    ),
) -> None:
    """단일 PDF를 처리한다."""

    config = ProcessingConfig(
        use_llm=use_llm,
        skip_existing_bookmarks=skip_existing_bookmarks,
        toc_detection=TocMlDetectionConfig(
            model_path=toc_model_path,
            probability_threshold=toc_probability_threshold,
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


@app.command()
def detect_bookmark_toc(
    input_dir: Path = typer.Argument(
        ..., help="PDF를 재귀적으로 찾을 입력 디렉터리다."
    ),
    output_json: Path | None = typer.Option(
        None,
        "--output-json",
        "-o",
        help="탐지 결과를 저장할 JSON 파일이다.",
    ),
    dataset_json: Path | None = typer.Option(
        None,
        "--dataset-json",
        help="page feature dataset row만 저장할 JSON 파일이다.",
    ),
    dataset_csv: Path | None = typer.Option(
        None,
        "--dataset-csv",
        help="page feature dataset row만 저장할 CSV 파일이다.",
    ),
    max_text_pages: int = typer.Option(
        80,
        "--max-text-pages",
        help="각 PDF 앞부분에서 TOC 탐지에 사용할 최대 page 수다.",
    ),
    min_total_pages: int = typer.Option(
        50,
        "--min-total-pages",
        min=1,
        help="이 page 수보다 짧은 PDF는 TOC 탐지와 dataset 생성을 건너뛴다.",
    ),
    random_seed: int = typer.Option(
        42,
        "--random-seed",
        help="negative page sampling을 재현하기 위한 난수 seed다.",
    ),
    workers: int = typer.Option(
        1,
        "--workers",
        min=1,
        help="PDF 파일 단위 병렬 처리 worker 수다.",
    ),
    recursive: bool = typer.Option(
        True,
        "--recursive/--no-recursive",
        help="하위 디렉터리까지 PDF를 찾는다.",
    ),
    diagnostics: bool = typer.Option(
        True,
        "--diagnostics/--quiet",
        help="진행 상황과 파일별 탐지 상태를 터미널에 출력한다.",
    ),
) -> None:
    """bookmark가 있는 PDF만 골라 TOC page detection을 실행한다."""

    result = BookmarkTocBatchDetector(
        input_dir,
        max_text_pages=max_text_pages,
        min_total_pages=min_total_pages,
        recursive=recursive,
        random_seed=random_seed,
        workers=workers,
        diagnostics=typer.echo if diagnostics else None,
    ).run()
    if output_json is not None:
        write_json(output_json, result)
    if dataset_json is not None:
        write_json(dataset_json, result.dataset_rows)
    if dataset_csv is not None:
        write_toc_page_dataset_csv(dataset_csv, result.dataset_rows)
    rich_print(
        to_jsonable(
            {
                "root_dir": result.root_dir,
                "workers": result.workers,
                "total_pdf_count": result.total_pdf_count,
                "bookmarked_pdf_count": result.bookmarked_pdf_count,
                "skipped_no_bookmark_count": result.skipped_no_bookmark_count,
                "skipped_short_pdf_count": result.skipped_short_pdf_count,
                "skipped_no_letter_bookmark_count": (
                    result.skipped_no_letter_bookmark_count
                ),
                "detected_count": result.detected_count,
                "not_detected_count": result.not_detected_count,
                "failed_count": result.failed_count,
                "dataset_row_count": result.dataset_row_count,
                "output_json": output_json,
                "dataset_json": dataset_json,
                "dataset_csv": dataset_csv,
            }
        )
    )


@app.command()
def train_toc_page_dataset(
    dataset: Path = typer.Argument(
        ..., help="detect-bookmark-toc로 생성한 TOC page dataset JSON/CSV 파일이다."
    ),
    output_dir: Path = typer.Option(
        Path("outputs/toc_page_dataset_model"),
        "--output-dir",
        "-o",
        help="학습된 모델과 train/test report를 저장할 디렉터리다.",
    ),
    model: str = typer.Option(
        "hist-gradient",
        "--model",
        help="decision-tree, hist-gradient, random-forest, all 중 하나다.",
    ),
    test_size: float = typer.Option(
        0.2,
        "--test-size",
        min=0.05,
        max=0.8,
        help="PDF group 기준 test split 비율이다.",
    ),
    random_seed: int = typer.Option(
        42,
        "--random-seed",
        help="train/test split과 모델 학습에 사용할 난수 seed다.",
    ),
) -> None:
    """생성된 TOC page dataset row로 classifier를 train/test한다."""

    if model not in {"decision-tree", "hist-gradient", "random-forest", "all"}:
        raise typer.BadParameter(
            "model은 decision-tree, hist-gradient, random-forest, all 중 하나여야 한다."
        )
    result = TocPageDatasetTrainer(
        dataset_path=dataset,
        output_dir=output_dir,
        model_type=cast(TocPageDatasetModelType, model),
        test_size=test_size,
        random_seed=random_seed,
    ).run()
    rich_print(to_jsonable(result))


def main() -> None:
    """콘솔 script entrypoint다."""

    app()


