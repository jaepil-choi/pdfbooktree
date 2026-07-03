"""experiment 051: Zvi 임의 페이지에서 Parse feature의 TOC page 분리력을 본다.

050은 Zvi TOC 줄에서 일반화 가능한 최소 feature table을 만들었다. 이 실험은 같은
Document Parse 구조 신호가 "이 페이지가 목차인가"라는 더 앞단의 page classification에도
쓸 수 있는지 확인한다.

설계:
- 양성: 사용자 제공 Zvi TOC page 7-16, 047 캐시를 우선 재사용한다.
- 음성: 같은 PDF에서 TOC 밖 page를 seed 고정 random으로 최소 30개 뽑아 새로 Parse한다.
- feature: category, element 길이/위치, word box line, pane/indent, numbering, trailing page
  같은 050 계열 신호를 page 단위로 집계한다.
- 평가: 구조 feature만 쓴 LOO logistic, lexicon 포함 LOO logistic, 단일 feature AUC를 본다.

실행:
    $env:PDFBOOKTREE_ALLOW_EXTERNAL_PARSE='1'
    uv run --with truststore python experiments/051_parse_feature_toc_page_separation_zvi.py

출력:
    experiments/outputs/051_parse_feature_toc_page_separation_zvi/
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import math
import os
import random
import re
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import numpy as np
import requests
from dotenv import load_dotenv
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import LeaveOneOut, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from pdfbooktree.utils.text_normalize import normalize_text

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
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "051_parse_feature_toc_page_separation_zvi"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
CACHE_DIR = OUTPUT_DIR / "cache"
TOC_CACHE_DIR = ROOT_DIR / "experiments" / "outputs" / "047_document_parse_output_formats_zvi" / "cache"

TARGET_ID = "zvi_bodie_investments"
UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
DIGITIZE_URL = f"{UPSTAGE_BASE_URL}/document-digitization"
OUTPUT_FORMATS = ["text", "html", "markdown"]
RENDER_DPI = 200
RANDOM_SEED = 20260703
NEGATIVE_SAMPLE_SIZE = 30

DROP_LINE_CATEGORIES = {"header", "footer", "footnote"}
ALLOW_EXTERNAL_PARSE = os.environ.get("PDFBOOKTREE_ALLOW_EXTERNAL_PARSE") == "1"

_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_FONT_SIZE = re.compile(r"font-size\s*:\s*([0-9.]+)px", re.IGNORECASE)
_OPEN_TAG = re.compile(r"<\s*([a-zA-Z][a-zA-Z0-9]*)\b")
_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_LETTER = re.compile(r"[A-Za-z가-힣]")
_TRAILING_PAGE = re.compile(r"\s+\d+(?:\s*[-–]\s*\d+)?\s*$")
_DECIMAL = re.compile(r"^(\d+(?:\.\d+)+)\b")
_INTEGER = re.compile(r"^(?:\(?(\d{1,3})\)?[\).]?)\s+")
_PART = re.compile(r"^(?:part|book|unit|section|부|편)\b", re.IGNORECASE)
_CHAPTER = re.compile(r"^(?:chapter|chap\.?|ch\.?|제\s*\d+\s*장|\d+\s*장)\b", re.IGNORECASE)
_TOC_WORD = re.compile(r"\b(contents|table of contents|brief contents)\b|목차|차례", re.IGNORECASE)


@dataclass
class LineRow:
    pdf_page: int
    element_id: str
    element_line_index: int
    column_index: int
    category: str
    html_max_font_size: float
    title_x: float
    page_width: float
    yc_norm: float
    text: str


def is_content_text(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped and (_HANGUL.search(stripped) or _LATIN2.search(stripped)))


def has_letter(text: str) -> bool:
    return bool(_LETTER.search(text))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


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


def page_count(pdf: Path) -> int:
    with fitz.open(pdf) as document:
        return int(document.page_count)


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


def parse_cache_path(cache_dir: Path, png: bytes, page_1based: int) -> Path:
    extra = {
        "output_formats": json.dumps(OUTPUT_FORMATS),
        "coordinates": "true",
        "words": "true",
    }
    digest = hashlib.sha1(png).hexdigest()[:16]
    tag = "document-parse_" + "_".join(f"{key}{value}" for key, value in sorted(extra.items()))
    tag = re.sub(r"[^0-9A-Za-z._-]+", "", tag)[:80]
    return cache_dir / f"page_{page_1based:03d}_{tag}_{digest}.json"


def parse_page_all_formats(png: bytes, page_1based: int) -> dict[str, Any]:
    """기존 047 TOC 캐시를 우선 읽고, 없으면 051 cache에 Document Parse 결과를 저장한다."""

    old_cache = parse_cache_path(TOC_CACHE_DIR, png, page_1based)
    if old_cache.exists():
        return json.loads(old_cache.read_text(encoding="utf-8"))

    cache = parse_cache_path(CACHE_DIR, png, page_1based)
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    if not ALLOW_EXTERNAL_PARSE:
        raise RuntimeError(
            "외부 Document Parse 호출이 필요하지만 PDFBOOKTREE_ALLOW_EXTERNAL_PARSE=1이 "
            "설정되지 않았다. 로컬 PDF 페이지 이미지가 Upstage API로 전송되는 작업이다."
        )

    data = {
        "model": "document-parse",
        "output_formats": json.dumps(OUTPUT_FORMATS),
        "coordinates": "true",
        "words": "true",
    }
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


def html_features(element: dict[str, Any]) -> dict[str, Any]:
    value = str((element.get("content") or {}).get("html") or "")
    tags = _OPEN_TAG.findall(value)
    sizes = [float(size) for size in _FONT_SIZE.findall(value)]
    return {
        "html_primary_tag": tags[0].lower() if tags else "",
        "html_max_font_size": max(sizes) if sizes else 0.0,
        "html_font_sizes": sizes,
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
            }
        )
    return rows


def group_words_to_lines(words: list[dict[str, Any]], *, page_height: float) -> list[dict[str, Any]]:
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
                "yc_norm": round(
                    float(np.mean([(word["y0"] + word["y1"]) / 2.0 for word in content]))
                    / page_height,
                    6,
                ),
            }
        )
    return lines


def split_columns(words: list[dict[str, Any]], page_width: float) -> list[list[dict[str, Any]]]:
    content = [word for word in words if is_content_text(word["text"])]
    if len(content) < 20:
        return [words]
    x_centers = sorted((word["x0"] + word["x1"]) / 2.0 for word in content)
    gaps = [
        (x_centers[index + 1] - x_centers[index], x_centers[index], x_centers[index + 1])
        for index in range(len(x_centers) - 1)
    ]
    candidates = [gap for gap in gaps if gap[0] >= page_width * 0.08]
    if not candidates:
        return [words]
    _gap, left, right = max(candidates, key=lambda item: item[0])
    split_at = (left + right) / 2.0
    left_words = [word for word in words if (word["x0"] + word["x1"]) / 2.0 < split_at]
    right_words = [word for word in words if (word["x0"] + word["x1"]) / 2.0 >= split_at]
    if len(left_words) < 5 or len(right_words) < 5:
        return [words]
    return [left_words, right_words]


def build_lines_from_words(
    response: dict[str, Any],
    pdf_page: int,
    page_width: float,
    page_height: float,
) -> list[LineRow]:
    out: list[LineRow] = []
    for element in response.get("elements", []):
        category = str(element.get("category") or "")
        if category in DROP_LINE_CATEGORIES:
            continue
        words = word_rows_from_element(element, page_width, page_height)
        if not words:
            continue
        features = html_features(element)
        for column_index, part in enumerate(split_columns(words, page_width)):
            for line_index, line in enumerate(group_words_to_lines(part, page_height=page_height)):
                text = normalize_text(line["text"])
                if not text or not has_letter(text):
                    continue
                out.append(
                    LineRow(
                        pdf_page=pdf_page,
                        element_id=str(element.get("id") or ""),
                        element_line_index=line_index,
                        column_index=column_index,
                        category=category,
                        html_max_font_size=safe_float(features["html_max_font_size"]),
                        title_x=safe_float(line["title_x"]),
                        page_width=page_width,
                        yc_norm=safe_float(line["yc_norm"]),
                        text=text,
                    )
                )
    return sorted(out, key=lambda line: (line.pdf_page, line.column_index, line.yc_norm, line.element_id))


def numbering_depth(text: str) -> int:
    title = _TRAILING_PAGE.sub("", normalize_text(text)).lstrip("•*-–— ")
    if not title:
        return -1
    if _PART.search(title):
        return 0
    if _CHAPTER.search(title):
        return 1
    decimal = _DECIMAL.search(title)
    if decimal:
        return len(decimal.group(1).split("."))
    if _INTEGER.search(title):
        return 1
    return -1


def element_line_lengths(lines: list[LineRow]) -> list[int]:
    counter: Counter[tuple[int, str]] = Counter((line.pdf_page, line.element_id) for line in lines)
    return [counter[(line.pdf_page, line.element_id)] for line in lines]


def page_feature_row(
    pdf_page: int,
    is_toc: bool,
    response: dict[str, Any],
    lines: list[LineRow],
) -> dict[str, Any]:
    categories = Counter(str(element.get("category") or "") for element in response.get("elements", []))
    line_categories = Counter(line.category for line in lines)
    total_elements = sum(categories.values()) or 1
    line_count = len(lines) or 1
    sizes = [line.html_max_font_size for line in lines if line.html_max_font_size > 0]
    depths = [numbering_depth(line.text) for line in lines]
    element_lens = element_line_lengths(lines)
    x_norms = [line.title_x / line.page_width for line in lines if line.page_width]
    ordered = sorted(lines, key=lambda line: (line.column_index, line.yc_norm))
    y_gaps = [
        right.yc_norm - left.yc_norm
        for left, right in zip(ordered, ordered[1:])
        if left.column_index == right.column_index
    ]
    content_text = " ".join(
        str((element.get("content") or {}).get("text") or "")
        or html_to_text(str((element.get("content") or {}).get("html") or ""))
        for element in response.get("elements", [])
    )
    trailing_count = sum(1 for line in lines if _TRAILING_PAGE.search(line.text))
    decimal_count = sum(1 for depth in depths if depth >= 2)
    ordered_count = sum(1 for depth in depths if depth >= 0)
    chapter_count = sum(1 for line in lines if _CHAPTER.search(line.text))
    category_index_lines = line_categories["index"]
    return {
        "pdf_page": pdf_page,
        "is_toc": int(is_toc),
        "element_count": sum(categories.values()),
        "line_count": len(lines),
        "category_index_ratio": categories["index"] / total_elements,
        "category_paragraph_ratio": categories["paragraph"] / total_elements,
        "category_heading_ratio": (
            sum(count for category, count in categories.items() if category.startswith("heading"))
            / total_elements
        ),
        "line_index_ratio": category_index_lines / line_count,
        "line_table_ratio": line_categories["table"] / line_count,
        "line_paragraph_ratio": line_categories["paragraph"] / line_count,
        "trailing_page_ratio": trailing_count / line_count,
        "numbering_any_ratio": ordered_count / line_count,
        "numbering_decimal_ratio": decimal_count / line_count,
        "chapter_marker_ratio": chapter_count / line_count,
        "html_font_max": max(sizes) if sizes else 0.0,
        "html_font_unique_count": len(set(sizes)),
        "html_large_font_ratio": sum(1 for size in sizes if size >= 18.0) / line_count,
        "element_len_mean_log": float(np.mean([math.log1p(value) for value in element_lens])) if element_lens else 0.0,
        "multi_line_element_ratio": sum(1 for value in element_lens if value >= 3) / line_count if element_lens else 0.0,
        "column_two_ratio": sum(1 for line in lines if line.column_index >= 1) / line_count,
        "x_indent_std_norm": float(np.std(x_norms)) if x_norms else 0.0,
        "x_indent_min_norm": min(x_norms) if x_norms else 0.0,
        "y_gap_median_norm": float(np.median(y_gaps)) if y_gaps else 0.0,
        "short_line_ratio": sum(1 for line in lines if len(line.text) <= 45) / line_count,
        "toc_keyword_present": int(bool(_TOC_WORD.search(content_text))),
    }


def choose_pages(label: dict[str, Any], total_pages: int) -> tuple[list[int], list[int]]:
    toc_pages = list(label["toc_pages"])
    toc_set = set(toc_pages)
    candidates = [page for page in range(1, total_pages + 1) if page not in toc_set]
    rng = random.Random(RANDOM_SEED)
    negative_pages = sorted(rng.sample(candidates, NEGATIVE_SAMPLE_SIZE))
    return toc_pages, negative_pages


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


def numeric_feature_names(rows: list[dict[str, Any]], *, include_lexicon: bool) -> list[str]:
    blocked = {"pdf_page", "is_toc"}
    if not include_lexicon:
        blocked.add("toc_keyword_present")
    return [
        key
        for key, value in rows[0].items()
        if key not in blocked and isinstance(value, (int, float))
    ]


def matrix(rows: list[dict[str, Any]], names: list[str]) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray([[float(row[name]) for name in names] for row in rows], dtype=float)
    y = np.asarray([int(row["is_toc"]) for row in rows], dtype=int)
    return x, y


def evaluate_logistic(rows: list[dict[str, Any]], *, include_lexicon: bool) -> dict[str, Any]:
    names = numeric_feature_names(rows, include_lexicon=include_lexicon)
    x, y = matrix(rows, names)
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(class_weight="balanced", solver="liblinear", random_state=RANDOM_SEED),
    )
    loo = LeaveOneOut()
    probabilities = cross_val_predict(model, x, y, cv=loo, method="predict_proba")[:, 1]
    pred = (probabilities >= 0.5).astype(int)
    cm = confusion_matrix(y, pred, labels=[0, 1])
    return {
        "include_lexicon": include_lexicon,
        "feature_names": names,
        "roc_auc": round(float(roc_auc_score(y, probabilities)), 4),
        "average_precision": round(float(average_precision_score(y, probabilities)), 4),
        "accuracy": round(float(accuracy_score(y, pred)), 4),
        "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y, pred, zero_division=0)), 4),
        "confusion_matrix": {
            "tn": int(cm[0, 0]),
            "fp": int(cm[0, 1]),
            "fn": int(cm[1, 0]),
            "tp": int(cm[1, 1]),
        },
        "scores": [
            {
                "pdf_page": int(row["pdf_page"]),
                "is_toc": int(row["is_toc"]),
                "probability": round(float(prob), 6),
                "predicted": int(prob >= 0.5),
            }
            for row, prob in zip(rows, probabilities)
        ],
    }


def univariate_auc(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names = numeric_feature_names(rows, include_lexicon=False)
    _x, y = matrix(rows, names)
    out: list[dict[str, Any]] = []
    for name in names:
        values = np.asarray([float(row[name]) for row in rows], dtype=float)
        if len(set(values.tolist())) <= 1:
            continue
        auc = float(roc_auc_score(y, values))
        direction = "high_is_toc"
        effective = auc
        if auc < 0.5:
            direction = "low_is_toc"
            effective = 1.0 - auc
        toc_values = [float(row[name]) for row in rows if int(row["is_toc"]) == 1]
        non_values = [float(row[name]) for row in rows if int(row["is_toc"]) == 0]
        out.append(
            {
                "feature": name,
                "auc": round(auc, 4),
                "effective_auc": round(effective, 4),
                "direction": direction,
                "toc_mean": round(float(np.mean(toc_values)), 6),
                "non_toc_mean": round(float(np.mean(non_values)), 6),
            }
        )
    return sorted(out, key=lambda row: row["effective_auc"], reverse=True)


def build_finding(summary: dict[str, Any]) -> str:
    structural = summary["models"]["structural_only"]
    lexicon = summary["models"]["with_lexicon"]
    top = summary["top_univariate_features"][:5]
    top_text = ", ".join(
        f"{row['feature']}({row['direction']}, auc={row['effective_auc']})" for row in top
    )
    return (
        f"Zvi TOC 10p + random non-TOC {NEGATIVE_SAMPLE_SIZE}p(seed={RANDOM_SEED})를 "
        "Document Parse로 비교했다. "
        f"structural_only LOO: auc={structural['roc_auc']} ap={structural['average_precision']} "
        f"f1={structural['f1']} cm={structural['confusion_matrix']}; "
        f"with_lexicon LOO: auc={lexicon['roc_auc']} ap={lexicon['average_precision']} "
        f"f1={lexicon['f1']} cm={lexicon['confusion_matrix']}; "
        f"상위 단일 구조 feature는 {top_text}."
    )


def record_experiment(summary: dict[str, Any], label: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "050의 Document Parse 최소 feature(category, element 위치/길이, pane/indent, "
            "numbering, trailing page)가 Zvi에서 TOC page와 non-TOC page를 구분하는 데도 "
            "도움이 되는지 확인한다. TOC page는 047 캐시를 재사용하고, TOC 밖 page는 "
            "seed 고정 random 30p 이상을 새로 Document Parse한다."
        ),
        "inputs": [label["input_pdf"]],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "experiments\\labels\\answer_toc_ranges_manual.json",
        "models": ["document-parse"],
        "output_formats": OUTPUT_FORMATS,
        "source_experiments": [
            "047_document_parse_output_formats_zvi",
            "050_generalized_minimal_feature_table_zvi",
        ],
        "selection": {
            "seed": RANDOM_SEED,
            "positive_toc_pages": summary["toc_pages"],
            "negative_random_pages": summary["negative_pages"],
        },
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
    total_pages = page_count(pdf)
    toc_pages, negative_pages = choose_pages(label, total_pages)
    all_pages = toc_pages + negative_pages
    sizes = page_size_by_number(pdf, all_pages)

    responses: dict[int, dict[str, Any]] = {}
    line_rows: list[dict[str, Any]] = []
    page_rows: list[dict[str, Any]] = []
    for pdf_page in all_pages:
        page_kind = "TOC" if pdf_page in set(toc_pages) else "non-TOC"
        print(f"... parse/read Zvi page {pdf_page} ({page_kind})", flush=True)
        png = render_png(pdf, pdf_page)
        response = parse_page_all_formats(png, pdf_page)
        responses[pdf_page] = response
        page_width, page_height = sizes[pdf_page]
        lines = build_lines_from_words(response, pdf_page, page_width, page_height)
        line_rows.extend(asdict(line) for line in lines)
        page_rows.append(page_feature_row(pdf_page, pdf_page in set(toc_pages), response, lines))

    page_rows = sorted(page_rows, key=lambda row: (row["is_toc"], row["pdf_page"]))
    top_features = univariate_auc(page_rows)
    models = {
        "structural_only": evaluate_logistic(page_rows, include_lexicon=False),
        "with_lexicon": evaluate_logistic(page_rows, include_lexicon=True),
    }
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "target_id": TARGET_ID,
        "total_pdf_pages": total_pages,
        "toc_pages": toc_pages,
        "negative_pages": negative_pages,
        "sample_size": len(page_rows),
        "positive_count": len(toc_pages),
        "negative_count": len(negative_pages),
        "models": models,
        "top_univariate_features": top_features,
    }
    summary["finding"] = build_finding(summary)

    write_csv(OUTPUT_DIR / "page_features.csv", page_rows)
    write_csv(OUTPUT_DIR / "line_features.csv", line_rows)
    write_csv(OUTPUT_DIR / "univariate_feature_auc.csv", top_features)
    write_csv(OUTPUT_DIR / "structural_only_scores.csv", models["structural_only"]["scores"])
    write_csv(OUTPUT_DIR / "with_lexicon_scores.csv", models["with_lexicon"]["scores"])
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    record_experiment(summary, label)

    print("\n=== exp 051: Parse feature TOC page separation on Zvi ===")
    print(f"toc_pages={toc_pages}")
    print(f"negative_pages={negative_pages}")
    for name, metric in models.items():
        print(
            f"- {name}: auc={metric['roc_auc']} ap={metric['average_precision']} "
            f"f1={metric['f1']} cm={metric['confusion_matrix']}"
        )
    print("top structural features:")
    for row in top_features[:8]:
        print(
            f"  {row['feature']}: effective_auc={row['effective_auc']} "
            f"{row['direction']} toc_mean={row['toc_mean']} non_toc_mean={row['non_toc_mean']}"
        )
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()


