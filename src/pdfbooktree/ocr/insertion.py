"""표준 OCR 삽입 모델을 원본 PDF 위 invisible text layer로 삽입한다."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import fitz
import pikepdf

from pdfbooktree.ocr.models import InsertableOcrPage, OcrBox

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

# line이 자연 font_size(rect.height*0.88)로 한 줄에 다 안 들어가면(주로
# overlay_mode="element" fallback의 문단/표 전체 병합 line, 드물게 substitute
# font(malgun.ttf)가 원본보다 넓게 렌더링되는 word/row line) bbox 폭 기준으로
# word-wrap하고 세로로 쌓는다. word 폭이 font_size에 선형 비례하므로 wrap_width>0,
# available_height>0만 있으면 font_size를 충분히 줄여 항상 다 들어갈 수 있다(실측:
# 수리통계학 637쪽 문자 커버리지 44.3% -> 101.3%, 637쪽 전부 100%+, experiments/087).
LINE_SPACING_FACTOR = 1.15
MIN_WRAP_WIDTH_PT = 20.0
FIT_MIN_FONT_SIZE_PT = 0.05
BINARY_SEARCH_ITER = 30


def write_overlay_pdf(
    insertable_pages: list[InsertableOcrPage],
    source_pdf: Path,
    output_pdf: Path,
    temp_dir: Path,
) -> None:
    """원본 PDF의 기존 text object를 제거하고 새 invisible OCR layer를 삽입한다."""

    source_pdf = source_pdf.resolve()
    output_pdf = output_pdf.resolve()
    if source_pdf == output_pdf:
        raise ValueError(f"입력 PDF와 출력 PDF는 같은 파일일 수 없다: {source_pdf}")
    temp_dir.mkdir(parents=True, exist_ok=True)
    stripped_pdf = temp_dir / "source_text_stripped.pdf"

    target_pages = {page.pdf_page for page in insertable_pages}
    _strip_text_objects(source_pdf, stripped_pdf, target_pages)
    document = fitz.open(stripped_pdf)
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{output_pdf.stem}.",
        suffix=".pdf",
        dir=output_pdf.parent,
    )
    os.close(handle)
    temporary_pdf = Path(temporary_name)
    temporary_pdf.unlink()
    try:
        _insert_invisible_lines(document, insertable_pages)
        document.save(
            temporary_pdf,
            garbage=4,
            deflate=True,
            deflate_fonts=True,
            use_objstms=1,
            compression_effort=100,
        )
        document.close()
        os.replace(temporary_pdf, output_pdf)
    finally:
        if not document.is_closed:
            document.close()
        temporary_pdf.unlink(missing_ok=True)


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
        # get_text() 추출은 회전(rotation) 여부와 무관하게 원본 MediaBox 크기로
        # clip한다. 0/180도 회전이면 mediabox == page.rect라 차이가 없지만, 90/270도
        # 회전(width/height가 서로 바뀜)에서는 TextWriter가 쓰는 page.rect보다 훨씬
        # 좁은 영역만 실제로 추출된다(실측: 수리통계학 637쪽 중 회전 3쪽, experiments/087).
        safe_bounds = fitz.Rect(0.0, 0.0, page.mediabox.width, page.mediabox.height)
        inserted_on_page = 0
        for element in page_model.elements:
            for line in element.lines:
                text = " ".join(line.text.split())
                if not text:
                    continue

                rect = _scale_rect(
                    line.bbox,
                    page_rect=page.rect,
                    width_px=page_model.width_px,
                    height_px=page_model.height_px,
                )

                wrapped_lines, font_size = _fit_line_text(
                    font, text, rect, safe_bounds, min_font_size, max_font_size
                )
                line_height = font_size * LINE_SPACING_FACTOR
                origin_x0 = min(
                    max(rect.x0, 0.0), safe_bounds.width - MIN_WRAP_WIDTH_PT
                )
                origin_y0 = min(rect.y0, safe_bounds.height - 1.0)
                for index, wrapped_text in enumerate(wrapped_lines):
                    baseline_y = origin_y0 + (index + 1) * line_height
                    writer.append(
                        (origin_x0, baseline_y),
                        wrapped_text,
                        font=font,
                        fontsize=font_size,
                    )
                    inserted_on_page += 1

        if inserted_on_page:
            writer.write_text(page, overlay=True, render_mode=3)


def _fit_line_text(
    font: fitz.Font,
    text: str,
    rect: fitz.Rect,
    safe_bounds: fitz.Rect,
    min_font_size: float,
    max_font_size: float,
) -> tuple[list[str], float]:
    """line을 wrap_width/available_height 안에 반드시 들어가는 font_size로 맞춘다.

    word 폭은 font_size에 선형 비례하므로, wrap_width>0과 available_height>0만
    있으면 font_size를 충분히 줄여 항상 들어갈 수 있다(단일 초과 토큰도 동일 원리로
    해결된다). 자연 font_size로 한 줄에 이미 들어가면(대다수의 정상 line) 그대로
    한 줄만 쓴다. safe_bounds는 get_text()가 실제로 clip하는 영역(MediaBox 기준)이지,
    TextWriter가 쓰는 page.rect(회전 반영)가 아니다.
    """

    words = text.split()
    if not words:
        return [], min_font_size

    x0 = min(max(rect.x0, 0.0), safe_bounds.width - MIN_WRAP_WIDTH_PT)
    y0 = min(rect.y0, safe_bounds.height - 1.0)
    wrap_width = max(MIN_WRAP_WIDTH_PT, min(rect.width, safe_bounds.width - x0 - 2.0))
    available_height = max(1.0, safe_bounds.height - y0 - 2.0)

    natural_font_size = max(min_font_size, min(max_font_size, rect.height * 0.88))
    single_line = " ".join(words)
    if font.text_length(single_line, fontsize=natural_font_size) <= wrap_width:
        return [single_line], natural_font_size

    lo, hi = FIT_MIN_FONT_SIZE_PT, natural_font_size
    best_font_size = lo
    best_lines = _wrap_words_to_width(font, words, wrap_width, lo)
    for _ in range(BINARY_SEARCH_ITER):
        mid = (lo + hi) / 2
        lines = _wrap_words_to_width(font, words, wrap_width, mid)
        if _fits_within_bounds(font, lines, mid, wrap_width, available_height):
            best_font_size = mid
            best_lines = lines
            lo = mid
        else:
            hi = mid
    return best_lines, best_font_size


def _fits_within_bounds(
    font: fitz.Font,
    lines: list[str],
    font_size: float,
    wrap_width: float,
    available_height: float,
) -> bool:
    if not lines:
        return True
    required_height = len(lines) * font_size * LINE_SPACING_FACTOR
    if required_height > available_height + 1e-6:
        return False
    max_line_width = max(font.text_length(line, fontsize=font_size) for line in lines)
    return max_line_width <= wrap_width + 0.5


def _wrap_words_to_width(
    font: fitz.Font, words: list[str], wrap_width: float, font_size: float
) -> list[str]:
    space_width = font.text_length(" ", fontsize=font_size) or font_size * 0.25
    lines: list[list[str]] = []
    current: list[str] = []
    current_width = 0.0
    for word in words:
        word_width = font.text_length(word, fontsize=font_size)
        candidate_width = (
            word_width if not current else current_width + space_width + word_width
        )
        if current and candidate_width > wrap_width:
            lines.append(current)
            current = [word]
            current_width = word_width
        else:
            current.append(word)
            current_width = candidate_width
    if current:
        lines.append(current)
    return [" ".join(line) for line in lines]


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
