"""OCR overlay 전처리 파이프라인을 조립한다."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import fitz

from pdfbooktree.ocr.cache import OcrCache, file_sha256
from pdfbooktree.ocr.config import OcrOverlayConfig
from pdfbooktree.ocr.insertion import write_overlay_pdf
from pdfbooktree.ocr.models import InsertableOcrPage, OcrOverlayResult
from pdfbooktree.ocr.registry import create_ocr_engine
from pdfbooktree.ocr.render import render_pdf_page, write_rendered_page_image
from pdfbooktree.ocr.stats import write_ocr_stats
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks
from pdfbooktree.utils.jsonio import write_json


class ExistingBookmarkConfirmationRequired(RuntimeError):
    """기존 bookmark가 있는 PDF에 OCR overwrite 확인이 없을 때 발생한다."""


class OcrOverlayBuilder:
    """OCR 결과를 이미지 PDF 위 invisible text layer로 다시 입힌다."""

    def __init__(self, config: OcrOverlayConfig) -> None:
        self.config = config
        self.input_pdf = Path(config.input_pdf)
        self.output_pdf = Path(config.output_pdf)
        self.output_dir = Path(config.output_dir)

    def run(self) -> OcrOverlayResult:
        """OCR overlay PDF와 stats artifact를 생성한다."""

        self._validate_output()
        self._validate_existing_bookmark_confirmation()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        write_json(self.output_dir / "ocr_overlay_config.json", asdict(self.config))

        with fitz.open(self.input_pdf) as document:
            page_count = document.page_count
        pages = self._target_pages(page_count)
        engine = create_ocr_engine(self.config.engine, self.config.engine_options)
        cache = OcrCache(self.output_dir / "document_parse_cache")
        input_hash = file_sha256(self.input_pdf)

        insertable_pages: list[InsertableOcrPage] = []
        image_paths: dict[int, Path] = {}
        cache_hit_count = 0
        cache_miss_count = 0
        rendered_dir = self.output_dir / "rendered_pages"

        for pdf_page in pages:
            rendered = render_pdf_page(self.input_pdf, pdf_page, self.config.render_dpi)
            image_paths[pdf_page] = write_rendered_page_image(rendered, rendered_dir)

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
                    raise FileNotFoundError(f"OCR raw cache가 없다: page={pdf_page}")
                raw_response = engine.recognize_page(rendered)
                cache.write_raw(raw_key, raw_response)
                cache_miss_count += 1
            else:
                cache_hit_count += 1

            insertable_key = cache.insertable_cache_key(
                raw_response=raw_response,
                adapter_version=engine.adapter_version,
            )
            insertable = None
            if self.config.cache_policy != "refresh":
                insertable = cache.read_insertable(insertable_key)
            if insertable is None:
                insertable = engine.to_insertable_page(raw_response, rendered)
                cache.write_insertable(insertable_key, insertable)
            insertable_pages.append(insertable)

        write_overlay_pdf(
            insertable_pages,
            image_paths,
            self.output_pdf,
            self.output_dir / "_overlay_pages",
            self.config.render_dpi,
        )
        stats_result = write_ocr_stats(
            insertable_pages,
            self.output_dir,
            self.output_pdf,
            include_word_stats=self.config.stats_word_level,
        )
        result = OcrOverlayResult(
            status="processed",
            input_pdf=self.input_pdf,
            output_pdf=self.output_pdf,
            output_dir=self.output_dir,
            page_count=page_count,
            processed_pages=pages,
            engine=engine.engine_id,
            cache_hit_count=cache_hit_count,
            cache_miss_count=cache_miss_count,
            page_stats_path=stats_result.page_stats_path,
            element_stats_path=stats_result.element_stats_path,
            line_stats_path=stats_result.line_stats_path,
            word_stats_path=stats_result.word_stats_path,
            warnings=[],
        )
        write_json(self.output_dir / "ocr_overlay_report.json", result)
        return result

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


