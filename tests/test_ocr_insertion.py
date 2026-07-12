from __future__ import annotations

from pathlib import Path

import fitz

from pdfbooktree.ocr.insertion import (
    FIT_MIN_FONT_SIZE_PT,
    LINE_SPACING_FACTOR,
    _fit_line_text,
    write_overlay_pdf,
)
from pdfbooktree.ocr.models import (
    InsertableOcrElement,
    InsertableOcrLine,
    InsertableOcrPage,
    OcrBox,
)


def make_pdf_with_invisible_text(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(20, 20, 80, 80), color=(1, 0, 0), fill=(1, 0, 0))
    page.insert_text((30, 120), "OLD OCR TEXT", fontsize=12, render_mode=3)
    second_page = doc.new_page(width=200, height=200)
    second_page.insert_text((30, 120), "UNCHANGED OCR TEXT", fontsize=12, render_mode=3)
    doc.save(path)
    doc.close()


def render_page_png(path: Path, pdf_page: int) -> bytes:
    doc = fitz.open(path)
    try:
        return doc[pdf_page - 1].get_pixmap(dpi=96, alpha=False).tobytes("png")
    finally:
        doc.close()


def extract_page_text(path: Path, pdf_page: int) -> str:
    doc = fitz.open(path)
    try:
        return doc[pdf_page - 1].get_text()
    finally:
        doc.close()


def test_write_overlay_pdf_strips_existing_text_and_preserves_page_render(
    tmp_path: Path,
) -> None:
    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    make_pdf_with_invisible_text(input_pdf)
    before_png = render_page_png(input_pdf, 1)

    page = InsertableOcrPage(
        pdf_page=1,
        width_px=200,
        height_px=200,
        width_pt=200,
        height_pt=200,
        source_engine="test",
        elements=[
            InsertableOcrElement(
                element_id="1",
                category="paragraph",
                bbox=OcrBox(30, 95, 170, 125),
                content_text="NEW OCR TEXT",
                lines=[
                    InsertableOcrLine(
                        text="NEW OCR TEXT",
                        bbox=OcrBox(30, 95, 170, 125),
                    )
                ],
                overlay_mode="element",
            )
        ],
    )

    write_overlay_pdf([page], input_pdf, output_pdf, tmp_path / "overlay_pages")

    output_text = extract_page_text(output_pdf, 1)
    assert "NEW OCR TEXT" in output_text
    assert "OLD OCR TEXT" not in output_text
    assert render_page_png(output_pdf, 1) == before_png
    assert "UNCHANGED OCR TEXT" in extract_page_text(output_pdf, 2)

    output_doc = fitz.open(output_pdf)
    try:
        assert output_doc.page_count == 2
    finally:
        output_doc.close()


def test_element_overlay_wraps_long_text_instead_of_clipping(tmp_path: Path) -> None:
    """element fallback의 문단 전체 텍스트가 bbox 폭을 넘어 page 밖으로 잘리지 않아야 한다.

    수정 전에는 폭 제한 없이 한 줄로 써서 get_text()가 page 밖 glyph를 버렸다
    (실측: 수리통계학 637쪽 문자 커버리지 44.3%, experiments/086 참고).
    """

    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(input_pdf)
    doc.close()

    words = [f"word{i}" for i in range(60)]
    content_text = " ".join(words)
    page = InsertableOcrPage(
        pdf_page=1,
        width_px=200,
        height_px=200,
        width_pt=200,
        height_pt=200,
        source_engine="test",
        elements=[
            InsertableOcrElement(
                element_id="1",
                category="paragraph",
                bbox=OcrBox(20, 20, 180, 180),
                content_text=content_text,
                lines=[
                    InsertableOcrLine(text=content_text, bbox=OcrBox(20, 20, 180, 180))
                ],
                overlay_mode="element",
            )
        ],
    )

    write_overlay_pdf([page], input_pdf, output_pdf, tmp_path / "overlay_pages")

    output_text = extract_page_text(output_pdf, 1)
    for word in words:
        assert word in output_text


def test_short_line_stays_single_line_regardless_of_mode(tmp_path: Path) -> None:
    """line이 자연 font_size로 이미 한 줄에 들어가면 overlay_mode와 무관하게 그대로 쓴다."""

    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(input_pdf)
    doc.close()

    page = InsertableOcrPage(
        pdf_page=1,
        width_px=200,
        height_px=200,
        width_pt=200,
        height_pt=200,
        source_engine="test",
        elements=[
            InsertableOcrElement(
                element_id="1",
                category="paragraph",
                bbox=OcrBox(30, 108, 170, 122),
                content_text="SINGLE VISUAL ROW",
                lines=[
                    InsertableOcrLine(
                        text="SINGLE VISUAL ROW", bbox=OcrBox(30, 108, 170, 122)
                    )
                ],
                overlay_mode="word",
            )
        ],
    )

    write_overlay_pdf([page], input_pdf, output_pdf, tmp_path / "overlay_pages")

    output_text = extract_page_text(output_pdf, 1)
    assert "SINGLE VISUAL ROW" in output_text


def test_word_mode_long_line_is_also_wrapped(tmp_path: Path) -> None:
    """word/row 모드도 자연 font_size로 한 줄에 안 들어가면 element처럼 wrap된다.

    substitute font(malgun.ttf)가 원본 OCR bbox 폭보다 넓게 렌더링되면 word/row
    line도 page 밖으로 넘칠 수 있어(experiments/087), overlay_mode로 wrap 여부를
    가르지 않는다.
    """

    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(input_pdf)
    doc.close()

    words = [f"tok{i}" for i in range(60)]
    content_text = " ".join(words)
    page = InsertableOcrPage(
        pdf_page=1,
        width_px=200,
        height_px=200,
        width_pt=200,
        height_pt=200,
        source_engine="test",
        elements=[
            InsertableOcrElement(
                element_id="1",
                category="paragraph",
                bbox=OcrBox(20, 20, 180, 40),
                content_text=content_text,
                lines=[
                    InsertableOcrLine(text=content_text, bbox=OcrBox(20, 20, 180, 40))
                ],
                overlay_mode="word",
            )
        ],
    )

    write_overlay_pdf([page], input_pdf, output_pdf, tmp_path / "overlay_pages")

    output_text = extract_page_text(output_pdf, 1)
    for word in words:
        assert word in output_text


def test_rotated_page_wraps_within_mediabox_not_page_rect(tmp_path: Path) -> None:
    """90도 회전 page에서는 page.rect가 아니라 MediaBox 폭 기준으로 잘리지 않아야 한다.

    PyMuPDF의 get_text()는 90/270도 회전 page에서 TextWriter가 쓰는 page.rect(회전
    반영, 가로로 넓음)가 아니라 원본 MediaBox(회전 미반영, 세로로 좁음) 크기로
    clip한다. bbox가 MediaBox 폭을 넘는 요소를 MediaBox 기준으로 wrap하지 않으면
    글자가 통째로 사라진다(실측: 수리통계학 637쪽 중 회전된 3쪽, experiments/087).
    """

    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=600)  # mediabox 300x600
    page.set_rotation(90)  # page.rect가 600x300으로 뒤집힌다
    doc.save(input_pdf)
    doc.close()

    words = [f"tok{i}" for i in range(80)]
    content_text = " ".join(words)
    ocr_page = InsertableOcrPage(
        pdf_page=1,
        width_px=600,
        height_px=300,
        width_pt=600,
        height_pt=300,
        source_engine="test",
        elements=[
            InsertableOcrElement(
                element_id="1",
                category="paragraph",
                # bbox가 MediaBox 폭(300)을 넘어 page.rect 폭(600)까지 뻗는다.
                bbox=OcrBox(20, 20, 560, 280),
                content_text=content_text,
                lines=[
                    InsertableOcrLine(text=content_text, bbox=OcrBox(20, 20, 560, 280))
                ],
                overlay_mode="element",
            )
        ],
    )

    write_overlay_pdf([ocr_page], input_pdf, output_pdf, tmp_path / "overlay_pages")

    output_text = extract_page_text(output_pdf, 1)
    for word in words:
        assert word in output_text


def test_fit_line_text_shrinks_to_fit_or_floor() -> None:
    """font_size 이분 탐색이 bbox 안에 들어가거나 하한에 도달해야 한다.

    rect.height/line_count처럼 매 반복 재계산하는 첫 구현은 font_size가 다시
    커지는 진동이 생겼다(experiments/086 첫 시도에서 페이지 1·457이 1% 미만
    커버리지로 남았던 원인). 이 테스트는 그 회귀를 막는다.
    """

    font = fitz.Font("helv")
    rect = fitz.Rect(0, 0, 50, 50)
    safe_bounds = fitz.Rect(0, 0, 300, 300)
    min_font_size, max_font_size = 3.0, 18.0
    text = " ".join(["word"] * 100)

    lines, font_size = _fit_line_text(
        font, text, rect, safe_bounds, min_font_size, max_font_size
    )

    # 실제 구현은 bbox 높이가 아니라 safe_bounds(page 하단까지)를 fitting 대상으로
    # 삼는다(experiments/087에서 검증된 zero-loss 보장 방식).
    available_height = safe_bounds.height - rect.y0 - 2.0
    assert FIT_MIN_FONT_SIZE_PT <= font_size <= max_font_size
    required_height = len(lines) * font_size * LINE_SPACING_FACTOR
    assert (
        required_height <= available_height + 1e-6
        or font_size <= FIT_MIN_FONT_SIZE_PT + 1e-6
    )
    assert sum(len(line.split()) for line in lines) == 100
