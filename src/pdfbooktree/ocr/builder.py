"""OCR overlay 전처리 파이프라인을 조립한다."""

from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path

import fitz

from pdfbooktree.ocr.cache import OcrCache, file_sha256
from pdfbooktree.ocr.config import OcrOverlayConfig
from pdfbooktree.ocr.insertion import write_overlay_pdf
from pdfbooktree.ocr.logger import NullOcrLogger, OcrLogger, OcrLogEvent, OcrLogLevel
from pdfbooktree.ocr.models import InsertableOcrPage, OcrOverlayResult
from pdfbooktree.ocr.registry import create_ocr_engine
from pdfbooktree.ocr.render import render_pdf_page, write_rendered_page_image
from pdfbooktree.ocr.stats import write_ocr_stats
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks
from pdfbooktree.utils.jsonio import write_json


class ExistingBookmarkConfirmationRequired(RuntimeError):
    """기존 bookmark가 있는 PDF에 OCR overwrite 확인이 없을 때 발생한다."""


class OcrOverlayBuilder:
    """OCR 결과를 원본 PDF 위 invisible text layer로 다시 입힌다."""

    def __init__(
        self,
        config: OcrOverlayConfig,
        logger: OcrLogger | None = None,
    ) -> None:
        self.config = config
        self.input_pdf = Path(config.input_pdf)
        self.output_pdf = Path(config.output_pdf)
        self.output_dir = Path(config.output_dir)
        self.logger = logger or NullOcrLogger()
        self._started_at = 0.0
        self._total_pages = 0
        self._completed_pages = 0
        self._cache_hit_count = 0
        self._cache_miss_count = 0

    def run(self) -> OcrOverlayResult:
        """OCR overlay PDF와 stats artifact를 생성한다."""

        self._started_at = time.monotonic()
        try:
            self._validate_output()
            self._emit("bookmark_check_start", None, "기존 bookmark 확인 시작")
            self._validate_existing_bookmark_confirmation()
            self._emit("bookmark_check_done", None, "기존 bookmark 확인 완료")
            self.output_dir.mkdir(parents=True, exist_ok=True)
            write_json(self.output_dir / "ocr_overlay_config.json", asdict(self.config))

            with fitz.open(self.input_pdf) as document:
                page_count = document.page_count
            pages = self._target_pages(page_count)
            self._total_pages = len(pages)
            self._emit(
                "start",
                None,
                f"OCR overlay 시작: input={self.input_pdf.name}, pages={len(pages)}, dpi={self.config.render_dpi}",
            )
            engine = create_ocr_engine(self.config.engine, self.config.engine_options)
            cache = OcrCache(self.output_dir / "document_parse_cache")
            input_hash = file_sha256(self.input_pdf)

            insertable_pages: list[InsertableOcrPage] = []
            rendered_dir = self.output_dir / "rendered_pages"

            for pdf_page in pages:
                self._emit("page_start", pdf_page, f"page {pdf_page} 처리 시작")
                self._emit(
                    "page_render_start", pdf_page, f"page {pdf_page} 렌더링 시작"
                )
                rendered = render_pdf_page(
                    self.input_pdf, pdf_page, self.config.render_dpi
                )
                write_rendered_page_image(rendered, rendered_dir)
                self._emit("page_render_done", pdf_page, f"page {pdf_page} 렌더링 완료")

                raw_key = cache.raw_cache_key(
                    input_pdf_hash=input_hash,
                    pdf_page=pdf_page,
                    render_dpi=self.config.render_dpi,
                    engine=engine.engine_id,
                    request_params=engine.request_params(),
                )
                raw_response = None
                if self.config.cache_policy != "refresh":
                    raw_response = cache.read_raw(raw_key)
                if raw_response is None:
                    if self.config.cache_policy == "only":
                        raise FileNotFoundError(
                            f"OCR raw cache가 없다: page={pdf_page}"
                        )
                    self._emit(
                        "ocr_call_start", pdf_page, f"page {pdf_page} OCR API 호출 시작"
                    )
                    raw_response = engine.recognize_page(rendered)
                    cache.write_raw(raw_key, raw_response)
                    self._cache_miss_count += 1
                    self._emit(
                        "ocr_call_done", pdf_page, f"page {pdf_page} OCR API 호출 완료"
                    )
                else:
                    self._cache_hit_count += 1
                    self._emit(
                        "raw_cache_hit", pdf_page, f"page {pdf_page} raw OCR cache hit"
                    )

                insertable_key = cache.insertable_cache_key(
                    raw_response=raw_response,
                    adapter_version=engine.adapter_version,
                )
                insertable = None
                if self.config.cache_policy != "refresh":
                    insertable = cache.read_insertable(insertable_key)
                if insertable is None:
                    self._emit(
                        "insertable_build_start",
                        pdf_page,
                        f"page {pdf_page} 표준 삽입 모델 생성 시작",
                    )
                    insertable = engine.to_insertable_page(raw_response, rendered)
                    cache.write_insertable(insertable_key, insertable)
                    self._emit(
                        "insertable_build_done",
                        pdf_page,
                        f"page {pdf_page} 표준 삽입 모델 생성 완료",
                    )
                else:
                    self._emit(
                        "insertable_cache_hit",
                        pdf_page,
                        f"page {pdf_page} 표준 삽입 모델 cache hit",
                    )
                insertable_pages.append(insertable)
                self._completed_pages += 1
                self._emit("page_done", pdf_page, f"page {pdf_page} 처리 완료")

            self._emit("overlay_write_start", None, "overlay PDF 생성 시작")
            write_overlay_pdf(
                insertable_pages,
                self.input_pdf,
                self.output_pdf,
                self.output_dir / "_overlay_pages",
            )
            self._emit("overlay_write_done", None, "overlay PDF 생성 완료")
            self._emit("stats_write_start", None, "OCR stats 저장 시작")
            stats_result = write_ocr_stats(
                insertable_pages,
                self.output_dir,
                self.output_pdf,
                include_word_stats=self.config.stats_word_level,
            )
            self._emit("stats_write_done", None, "OCR stats 저장 완료")
            result = OcrOverlayResult(
                status="processed",
                input_pdf=self.input_pdf,
                output_pdf=self.output_pdf,
                output_dir=self.output_dir,
                page_count=page_count,
                processed_pages=pages,
                engine=engine.engine_id,
                cache_hit_count=self._cache_hit_count,
                cache_miss_count=self._cache_miss_count,
                page_stats_path=stats_result.page_stats_path,
                element_stats_path=stats_result.element_stats_path,
                line_stats_path=stats_result.line_stats_path,
                word_stats_path=stats_result.word_stats_path,
                warnings=[],
            )
            write_json(self.output_dir / "ocr_overlay_report.json", result)
            self._emit("done", None, "OCR overlay 완료")
            return result
        except Exception as exc:
            self._emit("failed", None, f"OCR overlay 실패: {exc}", level="error")
            raise
        finally:
            self.logger.close()

    def _validate_output(self) -> None:
        if not self.input_pdf.exists():
            raise FileNotFoundError(f"입력 PDF가 없다: {self.input_pdf}")
        if self.output_pdf.exists() and not self.config.force:
            raise FileExistsError(
                f"출력 PDF가 이미 있다. 덮어쓰려면 --force를 사용한다: {self.output_pdf}"
            )

    def _validate_existing_bookmark_confirmation(self) -> None:
        """bookmark 보유 PDF는 명시 확인 없이는 OCR overwrite를 막는다."""

        bookmarks = extract_existing_bookmarks(self.input_pdf)
        if bookmarks and not self.config.confirm_bookmark_ocr_overwrite:
            raise ExistingBookmarkConfirmationRequired(
                f"기존 bookmark {len(bookmarks)}개가 있는 PDF다. "
                "OCR overlay는 기존 OCR text layer를 새 layer로 교체하는 새 PDF를 만들므로 "
                "명시 확인이 필요하다. CLI에서는 --confirm-bookmark-ocr-overwrite를 사용한다."
            )

    def _target_pages(self, page_count: int) -> list[int]:
        if self.config.pages is None:
            return list(range(1, page_count + 1))
        pages = sorted(dict.fromkeys(self.config.pages))
        invalid = [page for page in pages if page < 1 or page > page_count]
        if invalid:
            raise ValueError(f"PDF page 범위를 벗어난 page가 있다: {invalid}")
        return pages

    def _emit(
        self,
        event: str,
        pdf_page: int | None,
        message: str,
        *,
        level: OcrLogLevel = "info",
    ) -> None:
        elapsed = time.monotonic() - self._started_at if self._started_at else 0.0
        eta = self._estimated_remaining_sec(elapsed)
        self.logger.emit(
            OcrLogEvent(
                event=event,
                level=level,
                input_pdf=self.input_pdf,
                pdf_page=pdf_page,
                total_pages=self._total_pages,
                completed_pages=self._completed_pages,
                cache_hit_count=self._cache_hit_count,
                cache_miss_count=self._cache_miss_count,
                elapsed_sec=elapsed,
                estimated_remaining_sec=eta,
                message=message,
            )
        )

    def _estimated_remaining_sec(self, elapsed: float) -> float | None:
        if self._total_pages <= 0 or self._completed_pages <= 0:
            return None
        remaining_pages = max(0, self._total_pages - self._completed_pages)
        return (elapsed / self._completed_pages) * remaining_pages
