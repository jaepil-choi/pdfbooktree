"""page 단위 scan 신호(image coverage, visible/invisible 문자 수)를 추출한다."""

from __future__ import annotations

from dataclasses import dataclass

import fitz


# PDF text rendering mode(Tr) 중 실제로 화면에 paint되는 값이다.
# 3=invisible, 7=clip만 추가(그리지 않음)이라 제외한다.
VISIBLE_RENDER_MODES = frozenset({0, 1, 2, 4, 5, 6})

# page에서 가장 큰 단일 image가 이 비율 이상을 덮으면 그 page를 image-dominant로 본다.
IMAGE_COVERAGE_THRESHOLD = 0.85
# 이 문자 수 이상이 visible mode로 그려지면 page에 실제 시각적 문자가 있다고 본다.
VISIBLE_CHAR_THRESHOLD = 10
DEFAULT_MAX_SAMPLE_PAGES = 50


@dataclass(frozen=True)
class PageScanSignal:
    """단일 page의 image coverage와 visible/invisible 문자 수다."""

    pdf_page: int
    image_coverage_ratio: float
    visible_char_count: int
    invisible_char_count: int
    is_scan_like_page: bool
    reject_reasons: tuple[str, ...] = ()


def sample_page_indices(
    page_count: int, max_pages: int = DEFAULT_MAX_SAMPLE_PAGES
) -> list[int]:
    """문서 전체에 걸쳐 고르게 0-based page index를 뽑는다.

    body page로 편향되지 않도록 앞부분만 보지 않고 문서 전체를 균등 sampling한다.
    """

    if page_count <= max_pages:
        return list(range(page_count))
    step = page_count / max_pages
    return sorted({int(i * step) for i in range(max_pages)})


def analyze_page(page: fitz.Page) -> PageScanSignal:
    """page가 scan-like인지 판정할 신호를 계산한다.

    scan-like page는 시각적 내용이 사실상 하나의 큰 raster image이고, 그 위에
    실제로 화면에 그려지는(visible) 문자가 없는 page다. invisible OCR text
    overlay가 있어도(예: 스캐너 소프트웨어가 얹은 검색용 text layer) 그 문자는
    화면에 그려지지 않으므로 visible_char_count에 잡히지 않는다.
    """

    page_rect = page.rect
    page_area = page_rect.width * page_rect.height

    image_coverage_ratio = 0.0
    for info in page.get_image_info():
        clipped = fitz.Rect(info["bbox"]) & page_rect
        area = 0.0 if clipped.is_empty else clipped.width * clipped.height
        ratio = area / page_area if page_area else 0.0
        image_coverage_ratio = max(image_coverage_ratio, ratio)

    trace = page.get_texttrace()
    visible_char_count = sum(
        len(span["chars"]) for span in trace if span["type"] in VISIBLE_RENDER_MODES
    )
    invisible_char_count = sum(
        len(span["chars"]) for span in trace if span["type"] not in VISIBLE_RENDER_MODES
    )

    is_image_dominant = image_coverage_ratio >= IMAGE_COVERAGE_THRESHOLD
    has_visible_text = visible_char_count >= VISIBLE_CHAR_THRESHOLD
    is_scan_like_page = is_image_dominant and not has_visible_text

    reject_reasons: list[str] = []
    if not is_image_dominant:
        reject_reasons.append(
            f"image_coverage_ratio={image_coverage_ratio:.4f} < {IMAGE_COVERAGE_THRESHOLD}"
        )
    if has_visible_text:
        reject_reasons.append(
            f"visible_char_count={visible_char_count} >= {VISIBLE_CHAR_THRESHOLD}"
        )

    return PageScanSignal(
        pdf_page=page.number + 1,
        image_coverage_ratio=image_coverage_ratio,
        visible_char_count=visible_char_count,
        invisible_char_count=invisible_char_count,
        is_scan_like_page=is_scan_like_page,
        reject_reasons=tuple(reject_reasons),
    )
