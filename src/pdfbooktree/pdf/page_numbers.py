r"""본문 page 상/하위 band에서 인쇄된 page number 후보를 추출한다.

experiment 015에서 검증한 로직을 그대로 옮긴다. OCR이 "19"를 "1" "9"처럼 쪼개
놓아도 같은 줄(y 공유)에서 x 거리가 가까운 textbox를 병합해 본래 숫자를 복원하고,
글자가 섞인 run(예: running header `Part1...23`)에서도 `\d+` 그룹을 모두 후보로 뽑는다.
진짜 page number는 page마다 1씩 증가하므로 이후 offset 통계에서 가려진다.
"""

from __future__ import annotations

import re
from pathlib import Path

import fitz

from pdfbooktree.config import OffsetEstimationConfig
from pdfbooktree.models import BandPageNumber
from pdfbooktree.utils.page_numbers import from_pymupdf_index

# word bbox 튜플: (x0, y0, x1, y1, text)
_Word = tuple[float, float, float, float, str]

DIGITS_RE = re.compile(r"\d{1,4}")


def extract_page_numbers(text: str, max_number: int) -> list[int]:
    """병합된 run text에서 연결된 숫자 그룹을 모두 page number 후보로 뽑는다.

    글자가 섞여도 거르지 않는다. running header(`Part1...23`)여도 `\\d+` 그룹으로
    `23` 같은 후보가 그대로 나오고, page마다 1씩 증가하는 진짜 page number만
    이후 통계에서 이긴다. OCR이 쪼갠 "1" "9"는 병합 단계에서 이미 "19"로 합쳐진다.
    """

    numbers: list[int] = []
    for group in DIGITS_RE.findall(text):
        number = int(group)
        if 0 < number <= max_number:
            numbers.append(number)
    return numbers


def _group_into_lines(
    words: list[_Word], height: float, line_y_tolerance_ratio: float
) -> list[list[_Word]]:
    """band 안 word를 y 좌표가 비슷한 것끼리 같은 줄로 묶는다."""

    lines: list[dict[str, object]] = []
    for word in sorted(words, key=lambda w: ((w[1] + w[3]) / 2.0, w[0])):
        y_center = (word[1] + word[3]) / 2.0
        word_height = max(word[3] - word[1], 1.0)
        tolerance = max(line_y_tolerance_ratio * word_height, 0.006 * height)
        if lines and abs(y_center - float(lines[-1]["y_center"])) <= tolerance:
            current = lines[-1]
            count = int(current["count"])
            current["y_center"] = (float(current["y_center"]) * count + y_center) / (
                count + 1
            )
            current["count"] = count + 1
            current["words"].append(word)  # type: ignore[attr-defined]
        else:
            lines.append({"y_center": y_center, "count": 1, "words": [word]})
    return [list(line["words"]) for line in lines]  # type: ignore[arg-type]


def _merge_close_words(
    line_words: list[_Word], merge_gap_ratio: float
) -> list[dict[str, object]]:
    """한 줄 안에서 x 간격이 가까운 word를 이어붙여 token run을 만든다."""

    runs: list[list[_Word]] = []
    for word in sorted(line_words, key=lambda w: w[0]):
        if not runs:
            runs.append([word])
            continue
        previous = runs[-1][-1]
        gap = word[0] - previous[2]
        word_height = max(word[3] - word[1], previous[3] - previous[1], 1.0)
        if gap <= merge_gap_ratio * word_height:
            runs[-1].append(word)
        else:
            runs.append([word])

    merged: list[dict[str, object]] = []
    for run in runs:
        text = "".join(word[4] for word in run)
        x0 = min(word[0] for word in run)
        y0 = min(word[1] for word in run)
        x1 = max(word[2] for word in run)
        y1 = max(word[3] for word in run)
        merged.append({"text": text, "bbox": (x0, y0, x1, y1)})
    return merged


def _extract_band_numbers_from_page(
    page: fitz.Page, config: OffsetEstimationConfig
) -> list[dict[str, object]]:
    """단일 page의 상/하위 band에서 page number 후보를 좌표와 함께 추출한다."""

    rect = page.rect
    width = float(rect.width)
    height = float(rect.height)
    if width <= 0 or height <= 0:
        return []

    top_threshold = rect.y0 + config.band_ratio * height
    bottom_threshold = rect.y1 - config.band_ratio * height

    band_words: dict[str, list[_Word]] = {"top": [], "bottom": []}
    for x0, y0, x1, y1, word, *_ in page.get_text("words"):
        token = word.strip()
        if not token:
            continue
        y_center = (y0 + y1) / 2.0
        if y_center <= top_threshold:
            band_words["top"].append((x0, y0, x1, y1, token))
        elif y_center >= bottom_threshold:
            band_words["bottom"].append((x0, y0, x1, y1, token))

    candidates: list[dict[str, object]] = []
    for band, words in band_words.items():
        for line_words in _group_into_lines(
            words, height, config.line_y_tolerance_ratio
        ):
            for run in _merge_close_words(line_words, config.merge_gap_ratio):
                bx0, by0, bx1, by1 = run["bbox"]  # type: ignore[misc]
                for number in extract_page_numbers(str(run["text"]), config.max_number):
                    candidates.append(
                        {
                            "number": number,
                            "text": str(run["text"]),
                            "band": band,
                            "x_ratio": round(((bx0 + bx1) / 2.0 - rect.x0) / width, 3),
                            "y_ratio": round(((by0 + by1) / 2.0) / height, 3),
                        }
                    )
    return candidates


def extract_band_page_numbers(
    pdf_path: Path | str,
    config: OffsetEstimationConfig | None = None,
) -> list[BandPageNumber]:
    """PDF 본문 전체(또는 max_scan_pages)에서 band page number 후보를 추출한다."""

    config = config or OffsetEstimationConfig()
    results: list[BandPageNumber] = []
    with fitz.open(pdf_path) as document:
        limit = document.page_count
        if config.max_scan_pages is not None:
            limit = min(limit, config.max_scan_pages)
        for page_index in range(limit):
            page = document.load_page(page_index)
            pdf_page = from_pymupdf_index(page_index)
            for candidate in _extract_band_numbers_from_page(page, config):
                results.append(
                    BandPageNumber(
                        pdf_page=pdf_page,
                        number=int(candidate["number"]),  # type: ignore[arg-type]
                        text=str(candidate["text"]),
                        band=candidate["band"],  # type: ignore[arg-type]
                        x_ratio=float(candidate["x_ratio"]),  # type: ignore[arg-type]
                        y_ratio=float(candidate["y_ratio"]),  # type: ignore[arg-type]
                    )
                )
    return results
