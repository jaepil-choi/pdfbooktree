"""실험 118: heading 추출 parameter가 agent가 조절할 수 있는 축인지 확인한다.

이 라이브러리의 목적은 "모든 책에 맞는 정답 알고리즘"이 아니다. AI agent가
싸고 결정적으로 구조를 뽑아보고, 결과를 훑어 말이 되는지 판단한 뒤, parameter를
바꿔 그 책에 맞추는 것이다. 그래서 물어야 할 질문은 "어떤 기본값이 최적인가"가
아니라 "이 knob이 조절 가능한 축인가"다.

조절 가능한 축의 조건은 세 가지다.

1. 도달성: 그 책에 대해 말이 되는 지점이 parameter 범위 안에 존재하는가
2. 단조성: knob을 한 방향으로 움직이면 결과도 한 방향으로 움직이는가
3. 해석성: 값의 의미가 책마다 달라지지 않는가

실험 117에서 확인한 제약을 반영한다. overlay는 font size를 bbox에 맞춰 정하고
책마다 다른 값에서 clamp하므로, 절대 font size나 tier 번호는 책 사이에서 의미가
달라진다. 그래서 후보 knob은 전부 책 내부 상대값으로 정의한다.

Upstage document parse 전용 표시(``![image](``, 표 pipe)는 쓰지 않는다. 어떤 OCR
overlay든 주는 일반 정보만 사용한다.

측정만 하고 제품 코드는 건드리지 않는다.
"""

from __future__ import annotations

import collections
import json
import pathlib
import random
import re
import statistics
from typing import Any

from pdfbooktree.config import ProcessingConfig
from pdfbooktree.pipeline import analyze_pdf
from pdfbooktree.typography.margins import exclude_margin_artifacts

ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "118_heading_knob_steerability"
CORPUS_DIR = ROOT_DIR / "data" / "300STUDY_ocr_overlay" / "pdfs"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
RESULT_PATH = OUTPUT_DIR / "results.json"

SAMPLE_SIZE = 6
MIN_LINES = 800
SEED = 20260818

WORD_RE = re.compile(r"[A-Za-z\uac00-\ud7a3]+")

# agent가 훑어보고 "말이 되는" 장 간격이라고 볼 범위다. 정답이 아니라 조작
# 가능성을 판정하기 위한 눈금이며, 책마다 실제 장 수는 다를 수 있다.
SENSIBLE_PAGES_PER_HEADING = (5.0, 40.0)

# 후보 knob의 sweep 범위. 전부 책 내부 상대값이다.
SIZE_CLASS_DEPTHS = (1, 2, 3)
MAX_PER_PAGE_VALUES = (1, 2, 3, 5, 8, 999)
MIN_WORDS_VALUES = (1, 2)


def has_word(text: str | None) -> int:
    return len(WORD_RE.findall((text or "").strip()))


def size_classes(lines: list[Any]) -> list[float]:
    """책 내부 font size를 큰 순서의 이산 class 값으로 만든다.

    overlay가 bbox에 맞춰 size를 정하므로 값은 연속적이다. 정확한 tier 경계를
    찾는 대신, 실제로 등장하는 값을 큰 순서로 세어 상위 class만 쓴다.
    """

    counts = collections.Counter(round(float(line.font_size), 2) for line in lines)
    return sorted(counts, reverse=True)


def select(
    lines: list[Any],
    classes: list[float],
    depth: int,
    max_per_page: int,
    min_words: int,
) -> list[Any]:
    """상위 size class에서 페이지 희소성과 단어 수 조건으로 후보를 고른다."""

    accepted = set(classes[:depth])
    big = [line for line in lines if round(float(line.font_size), 2) in accepted]
    by_page: dict[int, list[Any]] = collections.defaultdict(list)
    for line in big:
        by_page[line.pdf_page].append(line)

    chosen: list[Any] = []
    for page, page_lines in by_page.items():
        if len(page_lines) > max_per_page:
            continue
        for line in sorted(page_lines, key=lambda item: item.y0):
            if has_word(line.text) >= min_words:
                chosen.append(line)
    return sorted(chosen, key=lambda item: (item.pdf_page, item.y0))


def sweep(lines: list[Any], total_pages: int) -> list[dict[str, Any]]:
    classes = size_classes(lines)
    rows: list[dict[str, Any]] = []
    for depth in SIZE_CLASS_DEPTHS:
        for max_per_page in MAX_PER_PAGE_VALUES:
            for min_words in MIN_WORDS_VALUES:
                chosen = select(lines, classes, depth, max_per_page, min_words)
                pages = {line.pdf_page for line in chosen}
                rows.append(
                    {
                        "size_class_depth": depth,
                        "max_headings_per_page": max_per_page,
                        "min_words": min_words,
                        "candidates": len(chosen),
                        "pages_with_candidate": len(pages),
                        "pages_per_heading": (
                            round(total_pages / len(chosen), 2) if chosen else None
                        ),
                    }
                )
    return rows


def monotonic_share(rows: list[dict[str, Any]], knob: str) -> float:
    """knob을 키울 때 후보 수가 줄지 않는 비율을 센다."""

    groups: dict[tuple, list[tuple[float, int]]] = collections.defaultdict(list)
    keys = [
        k
        for k in ("size_class_depth", "max_headings_per_page", "min_words")
        if k != knob
    ]
    for row in rows:
        groups[tuple(row[k] for k in keys)].append((row[knob], row["candidates"]))
    ok = 0
    total = 0
    for series in groups.values():
        series.sort()
        for (_, a), (_, b) in zip(series, series[1:], strict=False):
            total += 1
            if b >= a:
                ok += 1
    return round(ok / total, 3) if total else 0.0


def main() -> None:
    if not CORPUS_DIR.is_dir():
        raise RuntimeError(f"corpus directory가 없다: {CORPUS_DIR}")

    config = ProcessingConfig().typography
    candidates = sorted(CORPUS_DIR.rglob("*.pdf"))
    random.Random(SEED).shuffle(candidates)

    books: list[dict[str, Any]] = []
    for pdf_path in candidates:
        if len(books) >= SAMPLE_SIZE:
            break
        try:
            analysis = analyze_pdf(pdf_path, config)
        except Exception:  # noqa: BLE001 - 관측값으로 남긴다
            continue
        lines = exclude_margin_artifacts(analysis.lines, config)
        if len(lines) < MIN_LINES:
            continue

        rows = sweep(lines, analysis.total_pages)
        low, high = SENSIBLE_PAGES_PER_HEADING
        reachable = [
            row
            for row in rows
            if row["pages_per_heading"] is not None
            and low <= row["pages_per_heading"] <= high
        ]
        best = min(
            reachable,
            key=lambda row: abs(row["pages_per_heading"] - 15.0),
            default=None,
        )
        book = {
            "pdf": pdf_path.name,
            "pages": analysis.total_pages,
            "body_lines": len(lines),
            "settings_tried": len(rows),
            "settings_in_sensible_range": len(reachable),
            "reachable": bool(reachable),
            "example_setting": best,
            "monotonic_size_class_depth": monotonic_share(rows, "size_class_depth"),
            "monotonic_max_headings_per_page": monotonic_share(
                rows, "max_headings_per_page"
            ),
            "sweep": rows,
        }
        books.append(book)
        print(
            "[{}] reachable={} in-range={}/{} example={} {}".format(
                len(books),
                book["reachable"],
                book["settings_in_sensible_range"],
                book["settings_tried"],
                (
                    "depth=%s per_page=%s words=%s -> %s p/heading"
                    % (
                        best["size_class_depth"],
                        best["max_headings_per_page"],
                        best["min_words"],
                        best["pages_per_heading"],
                    )
                    if best
                    else "none"
                ),
                pdf_path.name[:34],
            )
        )

    summary = {
        "sampled_books": len(books),
        "books_with_reachable_setting": sum(1 for b in books if b["reachable"]),
        "median_settings_in_range": statistics.median(
            b["settings_in_sensible_range"] for b in books
        )
        if books
        else 0,
        "median_monotonic_size_class_depth": statistics.median(
            b["monotonic_size_class_depth"] for b in books
        )
        if books
        else 0,
        "median_monotonic_max_headings_per_page": statistics.median(
            b["monotonic_max_headings_per_page"] for b in books
        )
        if books
        else 0,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(
            {"experiment_id": EXPERIMENT_ID, "summary": summary, "books": books},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
