"""experiment 047: Zvi Bodie TOC에서 Document Parse output format을 최대한 활용한다.

046은 Document Parse의 word box만 y순으로 다시 묶었고, category/element/html/markdown
구조를 거의 버렸다. 이 실험은 Zvi Bodie의 수동 정답 TOC page range(7-16)를 고정하고
Document Parse를 ``output_formats=["text", "html", "markdown"]``로 호출해, API가 이미
주는 구조 신호가 계층/항목 복원에 어떤 힌트를 주는지 관찰한다.

평가 질문
- html/markdown을 함께 요청하면 element.content에 어떤 추가 구조가 생기는가?
- category(heading1/index/paragraph/footer), element bbox, html tag/style, markdown line이
  목차 줄/계층 복원에 쓸 수 있는 신호인가?
- word box를 전역 y순으로 재구성하는 방식보다 element-aware representation이 bookmark
  title을 더 잘 보존하는가?

주의
- 이 실험은 Document Parse API 분석용이며 LLM item extraction은 호출하지 않는다.
- Document OCR(model=ocr)는 과금 때문에 쓰지 않고 document-parse만 쓴다.

실행:
    uv run --with truststore python experiments/047_document_parse_output_formats_zvi.py

출력:
    experiments/outputs/047_document_parse_output_formats_zvi/
"""

from __future__ import annotations

import csv
import hashlib
import html
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

from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks, title_has_letter
from pdfbooktree.utils.text_normalize import normalize_for_match, normalize_text

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass


ROOT_DIR = Path(__file__).resolve().parents[1]
LABELS_PATH = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "047_document_parse_output_formats_zvi"
CACHE_DIR = OUTPUT_DIR / "cache"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "047_document_parse_output_formats_zvi"

TARGET_ID = "zvi_bodie_investments"
UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
DIGITIZE_URL = f"{UPSTAGE_BASE_URL}/document-digitization"
RENDER_DPI = 200
OUTPUT_FORMATS = ["text", "html", "markdown"]
PARSE_DROP_CATEGORIES = {"header", "footer", "footnote"}

_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_FONT_SIZE = re.compile(r"font-size\s*:\s*([0-9.]+)px", re.IGNORECASE)
_OPEN_TAG = re.compile(r"<\s*([a-zA-Z][a-zA-Z0-9]*)\b")
_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_DIGIT = re.compile(r"\d+")


def is_content_text(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped and (_HANGUL.search(stripped) or _LATIN2.search(stripped)))


def load_zvi_label() -> dict[str, Any]:
    data = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    for label in data["labels"]:
        if label["id"] == TARGET_ID:
            return label
    raise RuntimeError(f"{TARGET_ID} 라벨을 찾지 못했다.")


def render_png(pdf: Path, page_1based: int, dpi: int = RENDER_DPI) -> bytes:
    with fitz.open(pdf) as document:
        page = document.load_page(page_1based - 1)
        return page.get_pixmap(dpi=dpi).tobytes("png")


def page_size_by_number(pdf: Path, pages: list[int]) -> dict[int, tuple[float, float]]:
    out: dict[int, tuple[float, float]] = {}
    with fitz.open(pdf) as document:
        for pno in pages:
            page = document.load_page(pno - 1)
            out[pno] = (float(page.rect.width) or 1.0, float(page.rect.height) or 1.0)
    return out


def _api_key() -> str:
    key = os.environ.get("UPSTAGE_API_KEY")
    if not key:
        raise RuntimeError("UPSTAGE_API_KEY가 설정되지 않았다.")
    return key


def parse_page_all_formats(png: bytes, page_1based: int) -> dict[str, Any]:
    """text/html/markdown을 한 번에 요청하고 page image hash로 캐시한다."""

    extra = {
        "output_formats": json.dumps(OUTPUT_FORMATS),
        "coordinates": "true",
        "words": "true",
    }
    digest = hashlib.sha1(png).hexdigest()[:16]
    tag = "document-parse_" + "_".join(f"{key}{value}" for key, value in sorted(extra.items()))
    tag = re.sub(r"[^0-9A-Za-z._-]+", "", tag)[:80]
    cache = CACHE_DIR / f"page_{page_1based:03d}_{tag}_{digest}.json"
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
        cache.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(1.2)
        return out
    raise last_exc or RuntimeError("Document Parse 반복 429로 실패")


def coord_box(points: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
    if not points:
        return None
    xs = [float(point["x"]) for point in points]
    ys = [float(point["y"]) for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def html_to_text(value: str) -> str:
    value = _BR.sub("\n", value)
    value = _TAG.sub(" ", value)
    return html.unescape(value)


def split_clean_lines(value: str) -> list[str]:
    lines: list[str] = []
    for raw in value.splitlines():
        text = normalize_text(raw)
        if text:
            lines.append(text)
    return lines


def element_text(element: dict[str, Any], source: str) -> str:
    content = element.get("content") or {}
    if source == "text":
        return str(content.get("text") or "")
    if source == "html":
        return html_to_text(str(content.get("html") or ""))
    if source == "markdown":
        return str(content.get("markdown") or "")
    raise ValueError(source)


def html_features(element: dict[str, Any]) -> dict[str, Any]:
    value = str((element.get("content") or {}).get("html") or "")
    tags = _OPEN_TAG.findall(value)
    sizes = [float(size) for size in _FONT_SIZE.findall(value)]
    return {
        "html_tags": tags,
        "html_font_sizes": sizes,
        "html_primary_tag": tags[0].lower() if tags else None,
        "html_max_font_size": max(sizes) if sizes else None,
    }


def word_rows_from_element(
    element: dict[str, Any], page_width: float, page_height: float
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for word in element.get("words") or []:
        box = coord_box(word.get("coordinates") or [])
        if box is None:
            continue
        x0, y0, x1, y1 = box
        rows.append(
            {
                "text": str(word.get("text") or ""),
                "x0": x0 * page_width,
                "y0": y0 * page_height,
                "x1": x1 * page_width,
                "y1": y1 * page_height,
                "x0_norm": x0,
                "y0_norm": y0,
                "x1_norm": x1,
                "y1_norm": y1,
            }
        )
    return rows


def group_words_to_lines(
    words: list[dict[str, Any]], *, page_width: float, page_height: float
) -> list[dict[str, Any]]:
    """word box를 줄로 묶되, 호출자가 element/column 단위로 이미 잘라서 넣는다고 가정한다."""

    if not words:
        return []
    content_heights = [
        word["y1"] - word["y0"] for word in words if is_content_text(word["text"])
    ]
    all_heights = [word["y1"] - word["y0"] for word in words]
    med_h = float(np.median(content_heights or all_heights))
    y_gate = max(med_h * 0.6, 1e-6)

    ordered = sorted(words, key=lambda word: ((word["y0"] + word["y1"]) / 2.0, word["x0"]))
    groups: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    cur_yc: float | None = None
    for word in ordered:
        yc = (word["y0"] + word["y1"]) / 2.0
        if cur and cur_yc is not None and abs(yc - cur_yc) > y_gate:
            groups.append(cur)
            cur = []
        cur.append(word)
        cur_yc = float(np.mean([(item["y0"] + item["y1"]) / 2.0 for item in cur]))
    if cur:
        groups.append(cur)

    lines: list[dict[str, Any]] = []
    for group in groups:
        group = sorted(group, key=lambda word: word["x0"])
        content = [word for word in group if is_content_text(word["text"])]
        if not content:
            continue
        text = normalize_text(" ".join(word["text"] for word in group if word["text"].strip()))
        if not text:
            continue
        heights = [word["y1"] - word["y0"] for word in content]
        lines.append(
            {
                "text": text,
                "height": round(float(np.median(heights)), 4),
                "title_x": round(min(word["x0"] for word in content), 4),
                "page_width": page_width,
                "yc_norm": round(
                    float(np.mean([(word["y0"] + word["y1"]) / 2.0 for word in content]))
                    / page_height,
                    6,
                ),
            }
        )
    return lines


def split_columns(words: list[dict[str, Any]], page_width: float) -> list[list[dict[str, Any]]]:
    """큰 index element 내부의 2단 column을 x 분포로 나눈다."""

    content = [word for word in words if is_content_text(word["text"])]
    if len(content) < 20:
        return [words]
    x_centers = sorted((word["x0"] + word["x1"]) / 2.0 for word in content)
    gaps = [
        (x_centers[index + 1] - x_centers[index], x_centers[index], x_centers[index + 1])
        for index in range(len(x_centers) - 1)
    ]
    min_gap = page_width * 0.08
    candidates = [gap for gap in gaps if gap[0] >= min_gap]
    if not candidates:
        return [words]
    _gap, left, right = max(candidates, key=lambda item: item[0])
    split_at = (left + right) / 2.0
    left_words = [word for word in words if (word["x0"] + word["x1"]) / 2.0 < split_at]
    right_words = [word for word in words if (word["x0"] + word["x1"]) / 2.0 >= split_at]
    if len(left_words) < 5 or len(right_words) < 5:
        return [words]
    return [left_words, right_words]


def build_lines_from_source(
    responses: dict[int, dict[str, Any]],
    sizes: dict[int, tuple[float, float]],
    source: str,
) -> list[dict[str, Any]]:
    """element boundary/category를 보존한 content source별 line representation을 만든다."""

    out: list[dict[str, Any]] = []
    for pdf_page, response in responses.items():
        page_width, page_height = sizes[pdf_page]
        for element in response.get("elements", []):
            category = str(element.get("category") or "")
            if category in PARSE_DROP_CATEGORIES:
                continue
            box = coord_box(element.get("coordinates") or [])
            features = html_features(element)
            text_lines = split_clean_lines(element_text(element, source))
            if not text_lines:
                continue
            if box is None:
                element_x0 = element_y0 = element_x1 = element_y1 = None
            else:
                x0, y0, x1, y1 = box
                element_x0 = x0 * page_width
                element_y0 = y0 * page_height
                element_x1 = x1 * page_width
                element_y1 = y1 * page_height
            for index, text in enumerate(text_lines):
                out.append(
                    {
                        "source": source,
                        "pdf_page": pdf_page,
                        "element_id": element.get("id"),
                        "element_line_index": index,
                        "category": category,
                        "text": text,
                        "element_x0": element_x0,
                        "element_y0": element_y0,
                        "element_x1": element_x1,
                        "element_y1": element_y1,
                        "html_primary_tag": features["html_primary_tag"],
                        "html_max_font_size": features["html_max_font_size"],
                        "html_tags": ",".join(features["html_tags"]),
                    }
                )
    return out


def build_lines_from_words(
    responses: dict[int, dict[str, Any]],
    sizes: dict[int, tuple[float, float]],
    *,
    column_aware: bool,
) -> list[dict[str, Any]]:
    """word box 기반 line을 만들되 element/category와 선택적 column split을 보존한다."""

    out: list[dict[str, Any]] = []
    source = "word_element_columns" if column_aware else "word_element"
    for pdf_page, response in responses.items():
        page_width, page_height = sizes[pdf_page]
        for element in response.get("elements", []):
            category = str(element.get("category") or "")
            if category in PARSE_DROP_CATEGORIES:
                continue
            words = word_rows_from_element(element, page_width, page_height)
            if not words:
                continue
            partitions = split_columns(words, page_width) if column_aware else [words]
            features = html_features(element)
            for column_index, part in enumerate(partitions):
                for line_index, line in enumerate(
                    group_words_to_lines(part, page_width=page_width, page_height=page_height)
                ):
                    line.update(
                        {
                            "source": source,
                            "pdf_page": pdf_page,
                            "element_id": element.get("id"),
                            "element_line_index": line_index,
                            "column_index": column_index,
                            "category": category,
                            "html_primary_tag": features["html_primary_tag"],
                            "html_max_font_size": features["html_max_font_size"],
                            "html_tags": ",".join(features["html_tags"]),
                        }
                    )
                    out.append(line)
    return out


def bookmark_refs(pdf: Path) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for bookmark in extract_existing_bookmarks(pdf):
        title = str(bookmark.get("title") or "")
        if not title_has_letter(title):
            continue
        refs.append(
            {
                "title": title,
                "norm": normalize_for_match(title),
                "level": bookmark.get("level"),
                "page": bookmark.get("page"),
                "order": bookmark.get("order"),
            }
        )
    return refs


def title_recall_metrics(lines: list[dict[str, Any]], refs: list[dict[str, Any]]) -> dict[str, Any]:
    """line text가 기존 bookmark title을 얼마나 보존하는지 약한 recall로 본다."""

    choices: list[str] = []
    choice_to_line: dict[str, dict[str, Any]] = {}
    for line in lines:
        norm = normalize_for_match(str(line.get("text") or ""))
        if norm and norm not in choice_to_line:
            choices.append(norm)
            choice_to_line[norm] = line

    matched: list[dict[str, Any]] = []
    by_level_total = Counter(str(ref["level"]) for ref in refs)
    by_level_hit: Counter[str] = Counter()
    for ref in refs:
        if not ref["norm"]:
            continue
        result = process.extractOne(
            ref["norm"], choices, scorer=fuzz.token_set_ratio, score_cutoff=88.0
        )
        if not result:
            continue
        line = choice_to_line[result[0]]
        matched.append(
            {
                "bookmark_title": ref["title"],
                "bookmark_level": ref["level"],
                "bookmark_page": ref["page"],
                "line_text": line.get("text"),
                "line_page": line.get("pdf_page"),
                "category": line.get("category"),
                "score": float(result[1]),
            }
        )
        by_level_hit[str(ref["level"])] += 1

    return {
        "line_count": len(lines),
        "bookmark_ref_count": len(refs),
        "matched": len(matched),
        "recall": round(len(matched) / len(refs), 4) if refs else 0.0,
        "by_level": {
            level: {
                "matched": by_level_hit[level],
                "total": by_level_total[level],
                "recall": round(by_level_hit[level] / by_level_total[level], 4),
            }
            for level in sorted(by_level_total, key=lambda value: int(value))
        },
        "matches_preview": matched[:30],
    }


def response_stats(responses: dict[int, dict[str, Any]]) -> dict[str, Any]:
    page_stats: list[dict[str, Any]] = []
    total_categories: Counter[str] = Counter()
    total_tags: Counter[str] = Counter()
    font_sizes: list[float] = []
    for pdf_page, response in responses.items():
        categories = Counter()
        tags = Counter()
        page_font_sizes: list[float] = []
        content_lengths = {"text": 0, "html": 0, "markdown": 0}
        for key in content_lengths:
            content_lengths[key] = len(str((response.get("content") or {}).get(key) or ""))
        for element in response.get("elements", []):
            category = str(element.get("category") or "")
            categories[category] += 1
            total_categories[category] += 1
            features = html_features(element)
            tags.update(features["html_tags"])
            total_tags.update(features["html_tags"])
            page_font_sizes.extend(features["html_font_sizes"])
            font_sizes.extend(features["html_font_sizes"])
        page_stats.append(
            {
                "pdf_page": pdf_page,
                "element_count": len(response.get("elements", [])),
                "category_counts": dict(categories),
                "html_tag_counts": dict(tags),
                "html_font_sizes": sorted(set(page_font_sizes)),
                "top_level_content_lengths": content_lengths,
            }
        )
    return {
        "pages": page_stats,
        "category_counts": dict(total_categories),
        "html_tag_counts": dict(total_tags),
        "html_font_sizes": sorted(set(font_sizes)),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def write_previews(lines_by_source: dict[str, list[dict[str, Any]]]) -> None:
    preview_dir = OUTPUT_DIR / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    for source, lines in lines_by_source.items():
        out: list[str] = []
        for page in sorted({int(line["pdf_page"]) for line in lines}):
            out.append(f"=== PDF page {page} ===")
            for line in [row for row in lines if row["pdf_page"] == page][:80]:
                prefix = f"{line.get('category')}#{line.get('element_id')}"
                if "column_index" in line:
                    prefix += f"/c{line.get('column_index')}"
                out.append(f"{prefix}: {line.get('text')}")
            out.append("")
        (preview_dir / f"{source}.txt").write_text("\n".join(out), encoding="utf-8")


def build_finding(metrics: dict[str, Any], stats: dict[str, Any]) -> str:
    pieces = [
        "Zvi Bodie TOC page 7-16을 document-parse output_formats=['text','html','markdown']로 재호출했다.",
        f"category 분포는 {stats['category_counts']}이다.",
        f"html tag 분포는 {stats['html_tag_counts']}, html font-size set은 {stats['html_font_sizes']}이다.",
    ]
    for source in [
        "text",
        "html",
        "markdown",
        "word_element",
        "word_element_columns",
    ]:
        value = metrics[source]
        pieces.append(
            f"{source}: lines={value['line_count']} bookmark_title_recall={value['recall']} "
            f"matched={value['matched']}/{value['bookmark_ref_count']}"
        )
    return " || ".join(pieces)


def record_experiment(summary: dict[str, Any], label: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "Zvi Bodie 정답 TOC page range(7-16)를 대상으로 Document Parse를 "
            "output_formats=['text','html','markdown'], coordinates=true, words=true로 호출해 "
            "category/element/html/markdown/word box가 어떤 구조 신호를 주는지 분석한다. "
            "046의 word y순 재구성이 category와 element boundary를 버린 문제를 확인하고, "
            "element-aware text/html/markdown line과 column-aware word line의 bookmark title "
            "recall을 비교한다."
        ),
        "inputs": [label["input_pdf"]],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "experiments\\labels\\answer_toc_ranges_manual.json",
        "models": ["document-parse"],
        "output_formats": OUTPUT_FORMATS,
        "source_experiment": "046_parse_geometry_toc_hierarchy",
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
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    label = load_zvi_label()
    pdf = ROOT_DIR / label["input_pdf"]
    toc_pages = list(label["toc_pages"])
    sizes = page_size_by_number(pdf, toc_pages)

    responses: dict[int, dict[str, Any]] = {}
    for pdf_page in toc_pages:
        print(f"... parse Zvi page {pdf_page} with {OUTPUT_FORMATS}", flush=True)
        responses[pdf_page] = parse_page_all_formats(render_png(pdf, pdf_page), pdf_page)

    refs = bookmark_refs(pdf)
    stats = response_stats(responses)

    lines_by_source: dict[str, list[dict[str, Any]]] = {
        "text": build_lines_from_source(responses, sizes, "text"),
        "html": build_lines_from_source(responses, sizes, "html"),
        "markdown": build_lines_from_source(responses, sizes, "markdown"),
        "word_element": build_lines_from_words(responses, sizes, column_aware=False),
        "word_element_columns": build_lines_from_words(responses, sizes, column_aware=True),
    }
    metrics = {
        source: title_recall_metrics(lines, refs)
        for source, lines in lines_by_source.items()
    }

    write_previews(lines_by_source)
    for source, lines in lines_by_source.items():
        write_csv(OUTPUT_DIR / f"{source}_lines.csv", lines)
    element_rows: list[dict[str, Any]] = []
    for pdf_page, response in responses.items():
        for element in response.get("elements", []):
            features = html_features(element)
            content = element.get("content") or {}
            box = coord_box(element.get("coordinates") or [])
            element_rows.append(
                {
                    "pdf_page": pdf_page,
                    "element_id": element.get("id"),
                    "category": element.get("category"),
                    "box": json.dumps(box, ensure_ascii=False),
                    "text_len": len(str(content.get("text") or "")),
                    "html_len": len(str(content.get("html") or "")),
                    "markdown_len": len(str(content.get("markdown") or "")),
                    "word_count": len(element.get("words") or []),
                    "html_primary_tag": features["html_primary_tag"],
                    "html_max_font_size": features["html_max_font_size"],
                    "html_tags": ",".join(features["html_tags"]),
                    "text_preview": normalize_text(str(content.get("text") or ""))[:160],
                    "html_text_preview": normalize_text(html_to_text(str(content.get("html") or "")))[:160],
                    "markdown_preview": normalize_text(str(content.get("markdown") or ""))[:160],
                }
            )
    write_csv(OUTPUT_DIR / "elements.csv", element_rows)

    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "target_id": TARGET_ID,
        "toc_pages": toc_pages,
        "output_formats": OUTPUT_FORMATS,
        "response_stats": stats,
        "metrics": metrics,
        "finding": build_finding(metrics, stats),
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    record_experiment(summary, label)

    print("\n=== exp 047: Document Parse output formats on Zvi Bodie ===")
    print(f"category_counts={stats['category_counts']}")
    print(f"html_tag_counts={stats['html_tag_counts']}")
    print(f"html_font_sizes={stats['html_font_sizes']}")
    for source, value in metrics.items():
        print(
            f"- {source:20s}: lines={value['line_count']:4d} "
            f"bookmark_title_recall={value['recall']} "
            f"matched={value['matched']}/{value['bookmark_ref_count']}"
        )
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()

