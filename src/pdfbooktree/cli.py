"""Typer 기반 CLI entrypoint다."""

from __future__ import annotations

from pathlib import Path

import typer
from rich import print as rich_print

from pdfbooktree.batch import BatchProcessor
from pdfbooktree.config import ProcessingConfig
from pdfbooktree.processor import Processor
from pdfbooktree.toc.bookmark_batch import (
    BookmarkTocBatchDetector,
    write_toc_page_dataset_csv,
)
from pdfbooktree.utils.jsonio import to_jsonable
from pdfbooktree.utils.jsonio import write_json


app = typer.Typer(help="PDF 책의 TOC를 bookmark와 Markdown tree로 구조화한다.")


@app.command()
def process(
    pdf: Path = typer.Argument(..., help="처리할 PDF 파일이다."),
    output_dir: Path = typer.Option(
        Path("."), "--output-dir", "-o", help="출력 디렉터리다."
    ),
    use_llm: bool = typer.Option(False, "--use-llm", help="LLM fallback 사용 여부다."),
    skip_existing_bookmarks: bool = typer.Option(
        True,
        "--skip-existing-bookmarks/--no-skip-existing-bookmarks",
        help="기존 bookmark가 깔끔하면 처리하지 않는다.",
    ),
) -> None:
    """단일 PDF를 처리한다."""

    config = ProcessingConfig(
        use_llm=use_llm,
        skip_existing_bookmarks=skip_existing_bookmarks,
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


def main() -> None:
    """콘솔 script entrypoint다."""

    app()
