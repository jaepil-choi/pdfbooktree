"""표준 OCR 삽입 모델을 원본 PDF 위 invisible text layer로 삽입한다."""

from __future__ import annotations

from pathlib import Path

import fitz
import pikepdf

from pdfbooktree.ocr.models import InsertableOcrLine, InsertableOcrPage, OcrBox

TEXT_OBJECT_BEGIN = "BT"
TEXT_OBJECT_END = "ET"
DEFAULT_FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\malgun.ttf"),
    Path(r"C:\Windows\Fonts\arial.ttf"),
]

# invisible text font_size의 절대 clamp 하한/상한이다. page 세로 길이가
# REFERENCE_PAGE_HEIGHT_PT(US Letter 세로 길이) 이하인 정상 판형 책에는 그대로
# 적용되고, 그보다 큰 book(예: 스캔 도구가 page MediaBox를 픽셀 크기 그대로 잘못
# 잡은 경우)에서는 page 크기에 비례해 함께 커진다. 실측(300STUDY 정상 판형 책 대비
# page_rect가 2.5~3배 큰 책)에서 절대 clamp만 쓰면 본문 문단까지 18pt 벽에
# 부딪혀 heading/본문 구분 신호가 통째로 사라지는 문제를 이렇게 고쳤다.
MIN_FONT_SIZE_PT = 3.0
MAX_FONT_SIZE_PT = 18.0
REFERENCE_PAGE_HEIGHT_PT = 792.0


def write_overlay_pdf(
    insertable_pages: list[InsertableOcrPage],
    source_pdf: Path,
    output_pdf: Path,
    temp_dir: Path,
) -> None:
    """원본 PDF의 기존 text object를 제거하고 새 invisible OCR layer를 삽입한다."""

    if output_pdf.exists():
        output_pdf.unlink()
    temp_dir.mkdir(parents=True, exist_ok=True)
    stripped_pdf = temp_dir / "source_text_stripped.pdf"

    target_pages = {page.pdf_page for page in insertable_pages}
    _strip_text_objects(source_pdf, stripped_pdf, target_pages)
    document = fitz.open(stripped_pdf)
    try:
        _insert_invisible_lines(document, insertable_pages)
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        document.save(
            output_pdf,
            garbage=4,
            deflate=True,
            deflate_fonts=True,
            use_objstms=1,
            compression_effort=100,
        )
    finally:
        document.close()


def _strip_text_objects(
    input_pdf: Path,
    output_pdf: Path,
    target_pages: set[int],
) -> None:
    """overwrite 대상 page content stream에서 BT...ET text object를 통째로 제거한다."""

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with pikepdf.open(input_pdf) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            if page_index not in target_pages:
                continue
            try:
                instructions = pikepdf.parse_content_stream(page)
            except Exception:  # noqa: BLE001
                continue

            stripped = []
            in_text_object = False
            changed = False
            for operands, operator in instructions:
                op = str(operator)
                if op == TEXT_OBJECT_BEGIN:
                    in_text_object = True
                    changed = True
                    continue
                if in_text_object:
                    changed = True
                    if op == TEXT_OBJECT_END:
                        in_text_object = False
                    continue
                stripped.append((operands, operator))

            if changed:
                page.Contents = pdf.make_stream(
                    pikepdf.unparse_content_stream(stripped)
                )

        pdf.save(
            output_pdf,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )


def _insert_invisible_lines(
    document: fitz.Document,
    insertable_pages: list[InsertableOcrPage],
) -> None:
    font = _load_overlay_font()
    for page_model in insertable_pages:
        if page_model.pdf_page < 1 or page_model.pdf_page > document.page_count:
            continue

        page = document[page_model.pdf_page - 1]
        writer = fitz.TextWriter(page.rect)
        min_font_size, max_font_size = _page_relative_font_size_bounds(page.rect.height)
        inserted_on_page = 0
        for line in _iter_insertable_lines(page_model):
            text = " ".join(line.text.split())
            if not text:
                continue

            rect = _scale_rect(
                line.bbox,
                page_rect=page.rect,
                width_px=page_model.width_px,
                height_px=page_model.height_px,
            )
            font_size = max(min_font_size, min(max_font_size, rect.height * 0.88))
            writer.append(
                (rect.x0, rect.y1),
                text,
                font=font,
                fontsize=font_size,
            )
            inserted_on_page += 1

        if inserted_on_page:
            writer.write_text(page, overlay=True, render_mode=3)


def _iter_insertable_lines(page: InsertableOcrPage) -> list[InsertableOcrLine]:
    return [line for element in page.elements for line in element.lines]


def _page_relative_font_size_bounds(page_height_pt: float) -> tuple[float, float]:
    """page 세로 길이에 비례한 font_size clamp 하한/상한을 계산한다.

    REFERENCE_PAGE_HEIGHT_PT 이하 정상 판형은 scale=1.0이라 기존 절대 clamp
    [3.0, 18.0]과 동일하게 동작한다. page가 그보다 크면(예: source PDF의
    MediaBox가 실제 판형과 무관하게 커진 경우) 상한/하한이 함께 커져서, 본문
    line까지 절대 상한에 부딪혀 heading 신호가 사라지는 것을 막는다.
    """

    scale = max(1.0, page_height_pt / REFERENCE_PAGE_HEIGHT_PT)
    return MIN_FONT_SIZE_PT * scale, MAX_FONT_SIZE_PT * scale


def _scale_rect(
    box: OcrBox,
    *,
    page_rect: fitz.Rect,
    width_px: int,
    height_px: int,
) -> fitz.Rect:
    sx = page_rect.width / width_px
    sy = page_rect.height / height_px
    rect = fitz.Rect(
        box.x0 * sx,
        box.y0 * sy,
        box.x1 * sx,
        box.y1 * sy,
    )
    if rect.height < 2:
        rect.y1 = rect.y0 + 2
    if rect.width < 2:
        rect.x1 = rect.x0 + 2
    return rect


def _load_overlay_font() -> fitz.Font:
    for font_path in DEFAULT_FONT_CANDIDATES:
        if font_path.exists():
            return fitz.Font(fontfile=str(font_path))
    return fitz.Font("helv")
