"""experiment 046: Document Parse 좌표를 원본 page geometry처럼 취급한다.

041의 hybrid는 fitz 줄을 backbone으로 두고 Parse의 text/trailing_page만 이식했다.
따라서 최종 계층 feature(height/title_x/is_bold/font_type)는 여전히 fitz span bbox에
의존했다. 이 실험은 그 가정을 분리해 검증한다.

검증 질문
- fitz span bbox에서 계산한 height/title_x를 버리고, Document Parse word box 좌표만으로
  line geometry를 만들면 계층과 printed_page 채널이 동시에 살아나는가?

비교 arm
- fitz_baseline: 현재 src production과 같은 fitz-only 줄.
- fitz_geometry_parse_text: 041 hybrid와 같은 fitz geometry + Parse text/page number.
- parse_geometry: Document Parse word box를 page point 좌표로 환산해 height/title_x를 계산한 줄.

주의
- TOC range 탐지와 page offset 추정은 041과 동일하게 현재 src production을 그대로 쓴다.
- 이 실험의 관심사는 TOC item extraction 직전의 line geometry source다.
- Document OCR(model=ocr)는 과금 때문에 쓰지 않고 document-parse만 쓴다.

실행:
    uv run --with truststore python experiments/046_parse_geometry_toc_hierarchy.py

출력:
    experiments/outputs/046_parse_geometry_toc_hierarchy/
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import numpy as np
import requests
from dotenv import load_dotenv
from rapidfuzz import fuzz, process

from pdfbooktree.alignment.headings import extract_heading_candidates
from pdfbooktree.alignment.match import align_toc_items
from pdfbooktree.alignment.offset import OffsetEstimationError, estimate_page_offset
from pdfbooktree.alignment.ranges import calculate_content_ranges
from pdfbooktree.config import ProcessingConfig
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks, title_has_letter
from pdfbooktree.pdf.text import extract_page_texts, extract_selected_page_texts
from pdfbooktree.toc.detect import detect_toc_pages
from pdfbooktree.toc.features import calculate_page_features
from pdfbooktree.toc.llm_range_review import LlmTocRangeReviewer
from pdfbooktree.toc.staged_llm_extract import (
    ClusteredTocLine,
    SizeAwareStagedTocExtractor,
    extract_clustered_toc_lines,
)
from pdfbooktree.utils.text_normalize import normalize_for_match, normalize_text

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 사내 TLS 가로채기 프록시(self-signed root) 환경에서 Upstage 호출이 SSL 검증으로
# 막히는 경우를 피한다. verify=False는 쓰지 않는다.
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass


ROOT_DIR = Path(__file__).resolve().parents[1]
LABELS_PATH = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "046_parse_geometry_toc_hierarchy"
CACHE_DIR = ROOT_DIR / "experiments" / "outputs" / "040_upstage_parse_src_endtoend" / "cache"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "046_parse_geometry_toc_hierarchy"

TARGET_IDS = [
    "zvi_bodie_investments",
    "kim_econometrics_note1",
    "kim_econometrics_note2",
    "quant_world",
    "hankyung_reader",
]
BOOKMARKED_IDS = set(TARGET_IDS)

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
DIGITIZE_URL = f"{UPSTAGE_BASE_URL}/document-digitization"
RENDER_DPI = 200
PARSE_DROP_CATEGORIES = {"header", "footer", "footnote"}

DY_GATE = 0.05
TEXT_MIN = 50.0

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_DIGIT = re.compile(r"\d+")
_SUBSET = re.compile(r"^[A-Z]{6}\+")


def is_content_text(text: str) -> bool:
    """계층 판단에 쓸 수 있는 글자 token인지 판정한다."""

    stripped = text.strip()
    return bool(stripped and (_HANGUL.search(stripped) or _LATIN2.search(stripped)))


def base_font(name: str) -> str:
    """PDF subset prefix와 weight suffix를 제거한 font family를 반환한다."""

    return _SUBSET.sub("", name).split("-")[0].split(",")[0].lower()


def span_is_bold(span: dict[str, Any]) -> bool:
    """PyMuPDF span의 bold 신호를 읽는다."""

    return bool(span["flags"] & 2**4) or ("bold" in str(span["font"]).lower())


def last_int(text: str) -> int | None:
    """문자열 마지막 정수를 printed page 후보로 읽는다."""

    nums = _DIGIT.findall(text)
    return int(nums[-1]) if nums else None


def render_png(pdf: Path, page_1based: int, dpi: int = RENDER_DPI) -> bytes:
    """PDF page를 Document Parse 입력용 PNG bytes로 렌더링한다."""

    with fitz.open(pdf) as document:
        page = document.load_page(page_1based - 1)
        return page.get_pixmap(dpi=dpi).tobytes("png")


def page_size_by_number(pdf: Path, pages: list[int]) -> dict[int, tuple[float, float]]:
    """1-based page 번호별 PDF page width/height를 point 단위로 반환한다."""

    out: dict[int, tuple[float, float]] = {}
    with fitz.open(pdf) as document:
        for pno in sorted(set(pages)):
            page = document.load_page(pno - 1)
            out[pno] = (float(page.rect.width) or 1.0, float(page.rect.height) or 1.0)
    return out


def _api_key() -> str:
    key = os.environ.get("UPSTAGE_API_KEY")
    if not key:
        raise RuntimeError("UPSTAGE_API_KEY가 설정되지 않았다.")
    return key


def parse_page(png: bytes) -> dict[str, Any]:
    """Document Parse를 호출하고 page image hash 기준으로 캐시한다."""

    extra = {"output_formats": '["text"]', "coordinates": "true", "words": "true"}
    digest = hashlib.sha1(png).hexdigest()[:16]
    tag = "document-parse_" + "_".join(f"{k}{v}" for k, v in sorted(extra.items()))
    tag = re.sub(r"[^0-9A-Za-z._-]+", "", tag)[:60]
    cache = CACHE_DIR / f"{tag}_{digest}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    data = {"model": "document-parse", **extra}
    delay = 6.0
    last_exc: Exception | None = None
    for attempt in range(7):
        resp = requests.post(
            DIGITIZE_URL,
            headers={"Authorization": f"Bearer {_api_key()}"},
            files={"document": ("page.png", io.BytesIO(png), "image/png")},
            data=data,
            timeout=180,
        )
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", delay))
            print(f"      429 rate-limited, {wait:.0f}s 대기 (attempt {attempt + 1})", flush=True)
            time.sleep(wait)
            delay = min(delay * 1.6, 60.0)
            continue
        try:
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(delay)
            delay = min(delay * 1.6, 60.0)
            continue
        out = resp.json()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        time.sleep(1.2)
        return out
    raise last_exc or RuntimeError("Document Parse 반복 429로 실패")


def _coord_box(points: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
    if not points:
        return None
    xs = [float(point["x"]) for point in points]
    ys = [float(point["y"]) for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _parse_words(resp: dict[str, Any]) -> list[tuple[str, float, float, float, float]]:
    """Document Parse response에서 header/footer를 제외한 word boxes를 추출한다."""

    words: list[tuple[str, float, float, float, float]] = []
    for element in resp.get("elements", []):
        if element.get("category", "") in PARSE_DROP_CATEGORIES:
            continue
        for word in element.get("words", []) or []:
            box = _coord_box(word.get("coordinates") or [])
            if box is None:
                continue
            words.append((str(word.get("text", "")), *box))
    return words


def fitz_rows(pdf: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """041 hybrid 비교용 fitz line rows를 만든다."""

    out: list[dict[str, Any]] = []
    with fitz.open(pdf) as document:
        for pno in toc_pages:
            page = document.load_page(pno - 1)
            page_width = float(page.rect.width) or 1.0
            page_height = float(page.rect.height) or 1.0
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    spans = [span for span in line["spans"] if span["text"].strip()]
                    content_spans = [
                        span for span in spans if is_content_text(span["text"])
                    ]
                    if not content_spans:
                        continue
                    content_spans.sort(key=lambda span: span["bbox"][0])
                    head = content_spans[0]
                    heights = [
                        round(float(span["bbox"][3] - span["bbox"][1]), 2)
                        for span in content_spans
                    ]
                    parts = [span["text"].strip() for span in spans]
                    y0 = min(float(span["bbox"][1]) for span in content_spans)
                    y1 = max(float(span["bbox"][3]) for span in content_spans)
                    out.append(
                        {
                            "pdf_page": pno,
                            "text": normalize_text(" ".join(parts)),
                            "height": max(heights),
                            "title_x": round(float(head["bbox"][0]), 2),
                            "page_width": page_width,
                            "is_bold": span_is_bold(head),
                            "font_type": base_font(str(head["font"])),
                            "trailing_page": last_int(" ".join(parts)),
                            "yc_norm": ((y0 + y1) / 2.0) / page_height,
                        }
                    )
    return out


def parse_geometry_rows(pdf: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """Parse word boxes를 page point 좌표로 환산해 clustered line rows를 만든다."""

    sizes = page_size_by_number(pdf, toc_pages)
    out: list[dict[str, Any]] = []
    for pno in toc_pages:
        page_width, page_height = sizes[pno]
        words = _parse_words(parse_page(render_png(pdf, pno)))
        if not words:
            continue

        letter_heights = [
            (y1 - y0) * page_height
            for text, _x0, y0, _x1, y1 in words
            if is_content_text(text)
        ]
        all_heights = [(y1 - y0) * page_height for _text, _x0, y0, _x1, y1 in words]
        med_h = float(np.median(letter_heights or all_heights))
        y_gate_norm = max((med_h / page_height) * 0.6, 1e-6)

        ordered = sorted(words, key=lambda word: ((word[2] + word[4]) / 2.0, word[1]))
        groups: list[list[tuple[str, float, float, float, float]]] = []
        cur: list[tuple[str, float, float, float, float]] = []
        cur_yc: float | None = None
        for word in ordered:
            yc = (word[2] + word[4]) / 2.0
            if cur and cur_yc is not None and abs(yc - cur_yc) > y_gate_norm:
                groups.append(cur)
                cur = []
            cur.append(word)
            cur_yc = float(np.mean([(item[2] + item[4]) / 2.0 for item in cur]))
        if cur:
            groups.append(cur)

        for group in groups:
            group = sorted(group, key=lambda word: word[1])
            content = [word for word in group if is_content_text(word[0])]
            if not content:
                continue
            joined = " ".join(word[0].strip() for word in group if word[0].strip())
            text = normalize_text(joined)
            if not text:
                continue

            content_heights = [(word[4] - word[2]) * page_height for word in content]
            # OCR word box의 튀는 한 글자를 줄 높이로 삼지 않도록 중앙값을 쓴다.
            line_height = float(np.median(content_heights))
            title_x = min(word[1] for word in content) * page_width
            y_centers = [(word[2] + word[4]) / 2.0 for word in content]
            out.append(
                {
                    "pdf_page": pno,
                    "text": text,
                    "height": round(line_height, 4),
                    "title_x": round(title_x, 4),
                    "page_width": page_width,
                    "is_bold": False,
                    "font_type": "document_parse",
                    "trailing_page": last_int(joined),
                    "yc_norm": float(np.mean(y_centers)),
                }
            )
    return out


def transplant_parse_text(
    fitz_line_rows: list[dict[str, Any]], parse_line_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """041과 같은 fitz geometry + Parse text 이식 arm을 만든다."""

    parse_by_page: dict[int, list[int]] = {}
    for index, row in enumerate(parse_line_rows):
        parse_by_page.setdefault(row["pdf_page"], []).append(index)

    merged: list[dict[str, Any]] = []
    transplanted = 0
    for row in fitz_line_rows:
        candidates = parse_by_page.get(row["pdf_page"], [])
        fitz_norm = normalize_for_match(row["text"])
        best_index: int | None = None
        best_score = -1.0
        for index in candidates:
            parse_row = parse_line_rows[index]
            if parse_row.get("_used"):
                continue
            if abs(parse_row["yc_norm"] - row["yc_norm"]) > DY_GATE:
                continue
            score = fuzz.token_set_ratio(
                fitz_norm, normalize_for_match(parse_row["text"])
            )
            if score > best_score:
                best_score = score
                best_index = index

        new_row = dict(row)
        if best_index is not None and best_score >= TEXT_MIN:
            parse_line_rows[best_index]["_used"] = True
            new_row["text"] = parse_line_rows[best_index]["text"]
            new_row["trailing_page"] = parse_line_rows[best_index]["trailing_page"]
            transplanted += 1
        merged.append(new_row)
    return merged, {"fitz_lines": len(fitz_line_rows), "transplanted": transplanted}


def rows_to_clustered(rows: list[dict[str, Any]]) -> list[ClusteredTocLine]:
    """실험 row dict를 src extractor 입력 타입으로 변환한다."""

    return [
        ClusteredTocLine(
            pdf_page=row["pdf_page"],
            text=row["text"],
            height=row["height"],
            title_x=row["title_x"],
            page_width=row["page_width"],
            is_bold=row.get("is_bold", False),
            font_type=row.get("font_type", "unknown"),
            trailing_page=row.get("trailing_page"),
        )
        for row in rows
    ]


def clustered_to_rows(lines: list[ClusteredTocLine]) -> list[dict[str, Any]]:
    """src fitz baseline line을 공통 평가 row로 바꾼다."""

    return [
        {
            "pdf_page": line.pdf_page,
            "text": line.text,
            "height": line.height,
            "title_x": line.title_x,
            "page_width": line.page_width,
            "is_bold": line.is_bold,
            "font_type": line.font_type,
            "trailing_page": line.trailing_page,
        }
        for line in lines
    ]


def build_heading_candidates(
    pdf: Path,
    items: list[Any],
    offset: int | None,
    total_pages: int,
    window: int,
) -> dict[int, list[Any]]:
    """Processor._build_heading_candidates와 같은 방식으로 본문 heading 후보를 만든다."""

    if offset is None:
        return {}
    estimated_by_index: dict[int, int] = {}
    needed: set[int] = set()
    for index, item in enumerate(items):
        if item.printed_page is None:
            continue
        estimated = item.printed_page + offset
        estimated_by_index[index] = estimated
        for page in range(estimated - window, estimated + window + 1):
            if 1 <= page <= total_pages:
                needed.add(page)
    if not needed:
        return {}
    heading_pages = extract_selected_page_texts(pdf, sorted(needed))
    return {
        index: extract_heading_candidates(heading_pages, estimated, window)
        for index, estimated in estimated_by_index.items()
    }


class _OffsetView:
    def __init__(self, offset: int | None) -> None:
        self.offset = offset


def range_metrics(detected: list[int], gt: list[int]) -> dict[str, Any]:
    dset = set(detected)
    gset = set(gt)
    inter = len(dset & gset)
    return {
        "detected": detected,
        "gt": gt,
        "precision": round(inter / len(dset), 4) if dset else 0.0,
        "recall": round(inter / len(gset), 4) if gset else 0.0,
        "missing": sorted(gset - dset),
        "extra": sorted(dset - gset),
    }


def normalize_bookmark_levels(bookmarks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = [bookmark for bookmark in bookmarks if title_has_letter(bookmark["title"])]
    if not kept:
        return []
    min_level = min(bookmark["level"] for bookmark in kept)
    return [
        {
            "title": bookmark["title"],
            "level": bookmark["level"] - min_level + 1,
            "order": bookmark["order"],
        }
        for bookmark in kept
    ]


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


def weakref_metrics(items: list[Any], bookmarks: list[dict[str, Any]]) -> dict[str, Any]:
    ref = normalize_bookmark_levels(bookmarks)
    if not ref or not items:
        return {"bookmark_letter_count": len(ref), "matched": 0}

    norms = [normalize_for_match(item.title) for item in items]
    index_by_norm: dict[str, int] = {}
    choices: list[str] = []
    for index, norm in enumerate(norms):
        if norm and norm not in index_by_norm:
            index_by_norm[norm] = index
            choices.append(norm)

    pairs: list[tuple[dict[str, Any], Any]] = []
    for bookmark in ref:
        bookmark_norm = normalize_for_match(bookmark["title"])
        if not bookmark_norm:
            continue
        result = process.extractOne(
            bookmark_norm, choices, scorer=fuzz.token_set_ratio, score_cutoff=88.0
        )
        if result:
            pairs.append((bookmark, items[index_by_norm[result[0]]]))

    matched = len(pairs)
    abs_agree = sum(1 for bookmark, item in pairs if bookmark["level"] == item.level)
    ordered = sorted(pairs, key=lambda pair: pair[0]["order"])
    total_transitions = 0
    agreed_transitions = 0
    for (prev_bookmark, prev_item), (next_bookmark, next_item) in zip(
        ordered, ordered[1:]
    ):
        total_transitions += 1
        if _sign(next_bookmark["level"] - prev_bookmark["level"]) == _sign(
            next_item.level - prev_item.level
        ):
            agreed_transitions += 1

    return {
        "bookmark_letter_count": len(ref),
        "matched": matched,
        "match_rate": round(matched / len(ref), 4),
        "abs_level_agreement": round(abs_agree / matched, 4) if matched else None,
        "rel_depth_agreement": (
            round(agreed_transitions / total_transitions, 4)
            if total_transitions
            else None
        ),
    }


def page_metrics(items: list[Any]) -> dict[str, Any]:
    n_items = len(items)
    pages = [item.printed_page for item in items]
    have_pages = [page for page in pages if page is not None]
    total_pairs = 0
    monotonic_pairs = 0
    previous: int | None = None
    for page in pages:
        if page is None:
            continue
        if previous is not None:
            total_pairs += 1
            if page >= previous:
                monotonic_pairs += 1
        previous = page
    return {
        "items": n_items,
        "with_printed_page": len(have_pages),
        "coverage": round(len(have_pages) / n_items, 4) if n_items else 0.0,
        "monotonicity": round(monotonic_pairs / total_pairs, 4) if total_pairs else None,
    }


def hierarchy_metrics(items: list[Any]) -> dict[str, Any]:
    levels = [item.level for item in items]
    return {
        "item_count": len(items),
        "level_distribution": {
            str(level): count for level, count in sorted(Counter(levels).items())
        },
        "distinct_levels": len(set(levels)),
    }


def render_tree(items: list[Any]) -> list[str]:
    out: list[str] = []
    for item in items:
        indent = "    " * max(item.level - 1, 0)
        printed = item.printed_page if item.printed_page is not None else "-"
        out.append(f"{indent}[{printed}] L{item.level} {item.title}")
    return out


def safe_id(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", text).strip("_")[:80]


def run_arm(
    arm: str,
    rows: list[dict[str, Any]],
    offset_value: int | None,
    total_pages: int,
    pdf: Path,
    extractor: SizeAwareStagedTocExtractor,
    config: ProcessingConfig,
    bookmarks: list[dict[str, Any]] | None,
    match_stats: dict[str, int] | None = None,
) -> tuple[dict[str, Any], list[Any]]:
    """한 arm의 line rows를 TOC item과 bookmark placement까지 평가한다."""

    if not rows:
        return {"status": "no_lines"}, []
    items = extractor.extract_from_clustered_lines(rows_to_clustered(rows), None)
    if not items:
        return {"status": "no_items"}, []

    candidates = build_heading_candidates(
        pdf, items, offset_value, total_pages, config.heading_search_window
    )
    aligned = align_toc_items(items, _OffsetView(offset_value), candidates)
    ranges = calculate_content_ranges(aligned, total_pages)
    placeable = sum(1 for item in aligned if item.matched_pdf_page is not None)
    rec: dict[str, Any] = {
        "status": "ok",
        "line_count": len(rows),
        "hierarchy": hierarchy_metrics(items),
        "page_channel": page_metrics(items),
        "bookmark": {
            "items": len(items),
            "placeable": placeable,
            "placeable_ratio": round(placeable / len(items), 4) if items else 0.0,
            "ranges": len(ranges),
        },
        "tree_preview": render_tree(items)[:24],
    }
    if match_stats is not None:
        rec["match_stats"] = match_stats
    if bookmarks is not None:
        rec["weakref"] = weakref_metrics(items, bookmarks)
    return rec, items


def run_book(label: dict[str, Any], config: ProcessingConfig) -> dict[str, Any]:
    """한 PDF에 대해 세 geometry arm을 실행한다."""

    pdf = ROOT_DIR / label["input_pdf"]
    cid = safe_id(label["id"])
    rec: dict[str, Any] = {
        "id": label["id"],
        "input_pdf": label["input_pdf"],
        "arms": {},
    }
    if not pdf.exists():
        rec["status"] = "missing_pdf"
        return rec

    with fitz.open(pdf) as document:
        total_pages = document.page_count

    # 1) TOC range 탐지는 현재 src production 그대로 사용한다.
    pages = extract_page_texts(pdf, max_pages=config.max_toc_search_pages)
    features = calculate_page_features(pages, total_pages)
    toc_detection = detect_toc_pages(features, config.toc_detection)
    review = LlmTocRangeReviewer(config.llm_range_review).review(
        pdf, toc_detection, total_pages
    )
    toc_pages = review.pages if review.pages else toc_detection.pages
    rec["toc_pages"] = toc_pages
    rec["range_vs_gt"] = range_metrics(toc_pages, label.get("toc_pages", []))
    if not toc_pages:
        rec["status"] = "no_toc_pages"
        return rec

    # 2) offset도 현재 src production과 동일하게 둔다.
    try:
        offset_estimate = estimate_page_offset(pdf, config.offset)
        offset_value = offset_estimate.offset
        rec["offset"] = {
            "offset": offset_value,
            "confidence": offset_estimate.confidence,
        }
    except OffsetEstimationError as exc:
        offset_value = None
        rec["offset"] = {"offset": None, "confidence": 0.0, "error": str(exc)[:200]}

    # 3) line source만 arm별로 바꾼다.
    fitz_line_rows = clustered_to_rows(extract_clustered_toc_lines(pdf, toc_pages))
    fitz_match_rows = fitz_rows(pdf, toc_pages)
    parse_rows = parse_geometry_rows(pdf, toc_pages)
    fitz_parse_rows, match_stats = transplant_parse_text(
        fitz_match_rows, [dict(row) for row in parse_rows]
    )

    rows_by_arm = {
        "fitz_baseline": fitz_line_rows,
        "fitz_geometry_parse_text": fitz_parse_rows,
        "parse_geometry": parse_rows,
    }

    bookmarks = extract_existing_bookmarks(pdf) if label["id"] in BOOKMARKED_IDS else None
    extractor = SizeAwareStagedTocExtractor(config.llm_staged_extraction)

    for arm, rows in rows_by_arm.items():
        try:
            arm_rec, items = run_arm(
                arm,
                rows,
                offset_value,
                total_pages,
                pdf,
                extractor,
                config,
                bookmarks,
                match_stats if arm == "fitz_geometry_parse_text" else None,
            )
        except Exception as exc:  # noqa: BLE001
            rec["arms"][arm] = {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }
            continue
        rec["arms"][arm] = arm_rec
        if items:
            (OUTPUT_DIR / f"{cid}_{arm}_tree.txt").write_text(
                "\n".join(render_tree(items)) + "\n", encoding="utf-8"
            )

    rec["status"] = "ok"
    return rec


def build_finding(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for result in results:
        if result.get("status") != "ok":
            parts.append(f"{result['id']}: {result.get('status')}")
            continue
        range_result = result["range_vs_gt"]
        segment = [
            (
                f"{result['id']}(range P{range_result['precision']}/"
                f"R{range_result['recall']}, offset={result['offset'].get('offset')})"
            )
        ]
        for arm in ("fitz_baseline", "fitz_geometry_parse_text", "parse_geometry"):
            arm_result = result["arms"].get(arm, {})
            if arm_result.get("status") != "ok":
                segment.append(f"{arm}={arm_result.get('status')}")
                continue
            page_channel = arm_result["page_channel"]
            bookmark = arm_result["bookmark"]
            piece = (
                f"{arm}: cov {page_channel['with_printed_page']}/"
                f"{page_channel['items']}({page_channel['coverage']}) "
                f"mono={page_channel['monotonicity']} "
                f"placeable={bookmark['placeable']}/{bookmark['items']}"
            )
            if arm == "fitz_geometry_parse_text" and "match_stats" in arm_result:
                stats = arm_result["match_stats"]
                piece += f" transplanted={stats['transplanted']}/{stats['fitz_lines']}"
            weakref = arm_result.get("weakref", {})
            if weakref.get("matched"):
                piece += (
                    f" rel={weakref.get('rel_depth_agreement')}"
                    f" abs={weakref.get('abs_level_agreement')}"
                )
            segment.append(piece)
        parts.append("; ".join(segment))
    return " || ".join(parts)


def record_experiment(summary: dict[str, Any]) -> None:
    """experiments.json에 046 실행 기록을 갱신한다."""

    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "041 hybrid가 fitz geometry(height/title_x/is_bold/font_type)를 유지한 채 "
            "Document Parse text/trailing_page만 이식했던 한계를 분리해, Document Parse "
            "word box 좌표를 page point 좌표처럼 환산하고 height/title_x까지 Parse가 소유하는 "
            "parse_geometry arm을 검증한다. TOC range 탐지와 offset은 src production을 "
            "그대로 두고, fitz_baseline / fitz_geometry_parse_text / parse_geometry 세 arm을 "
            "계층 weakref, printed page coverage/monotonicity, bookmark placeable로 비교한다."
        ),
        "inputs": [label["input_pdf"] for label in summary["_labels_used"]],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "experiments\\labels\\answer_toc_ranges_manual.json",
        "models": ["document-parse", "solar-pro3"],
        "temperature": 0.0,
        "source_experiment": "041_parse_fitz_hybrid_lines",
        "finding": summary["finding"],
        "ran_at": summary["ran_at"],
    }
    experiments = data.get("experiments", data) if isinstance(data, dict) else data
    experiments = [
        experiment for experiment in experiments if experiment.get("id") != EXPERIMENT_ID
    ]
    experiments.append(entry)
    if isinstance(data, dict):
        data["experiments"] = experiments
    else:
        data = experiments
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    load_dotenv(ROOT_DIR / ".env")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config = ProcessingConfig(use_llm=True)
    labels = {
        label["id"]: label
        for label in json.loads(LABELS_PATH.read_text(encoding="utf-8"))["labels"]
    }
    used = [labels[target_id] for target_id in TARGET_IDS if target_id in labels]

    results: list[dict[str, Any]] = []
    for label in used:
        print(f"... running {label['id']}", flush=True)
        try:
            results.append(run_book(label, config))
        except Exception as exc:  # noqa: BLE001
            print(f"    !! {label['id']} 실패: {type(exc).__name__}: {exc}", flush=True)
            results.append(
                {
                    "id": label["id"],
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        (OUTPUT_DIR / "summary_partial.json").write_text(
            json.dumps({"results": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "finding": build_finding(results),
        "results": results,
        "_labels_used": used,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(
            {key: value for key, value in summary.items() if key != "_labels_used"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    record_experiment(summary)

    print("\n=== exp 046: Document Parse geometry as page geometry ===")
    for result in results:
        if result.get("status") != "ok":
            print(f"\n- {result['id']} ({result.get('status')}) {result.get('error', '')}")
            continue
        range_result = result["range_vs_gt"]
        print(
            f"\n- {result['id']}  toc_pages={result['toc_pages']} "
            f"(GT P{range_result['precision']}/R{range_result['recall']})  "
            f"offset={result['offset'].get('offset')}"
        )
        for arm in ("fitz_baseline", "fitz_geometry_parse_text", "parse_geometry"):
            arm_result = result.get("arms", {}).get(arm, {})
            if arm_result.get("status") != "ok":
                print(f"    {arm:24s}: {arm_result.get('status')} {arm_result.get('error', '')}")
                continue
            page_channel = arm_result["page_channel"]
            hierarchy = arm_result["hierarchy"]
            bookmark = arm_result["bookmark"]
            line = (
                f"    {arm:24s}: items={page_channel['items']:3d} "
                f"cov={page_channel['with_printed_page']}/{page_channel['items']}"
                f"({page_channel['coverage']}) mono={page_channel['monotonicity']} "
                f"placeable={bookmark['placeable']}/{bookmark['items']} "
                f"levels={hierarchy['level_distribution']}"
            )
            if arm == "fitz_geometry_parse_text" and "match_stats" in arm_result:
                stats = arm_result["match_stats"]
                line += f" transplanted={stats['transplanted']}/{stats['fitz_lines']}"
            weakref = arm_result.get("weakref", {})
            if weakref.get("matched"):
                line += (
                    f" rel={weakref.get('rel_depth_agreement')}"
                    f" abs={weakref.get('abs_level_agreement')}"
                )
            print(line)
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
