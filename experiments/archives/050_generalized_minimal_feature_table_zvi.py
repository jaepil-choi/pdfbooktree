"""experiment 050: Zvi TOC line을 일반화 가능한 최소 feature table로 변환한다.

048/049는 Zvi 계층 점수를 올리기 위해 일부 rule이 과하게 붙었다. 이 실험은 성능 개선
rule을 추가하지 않고, 이후 작은 데이터에서도 쓸 수 있도록 sparse categorical을 줄인
최소 feature table을 만든다.

feature contract
- font_tier: TOC 내부 html_max_font_size를 1D KDE valley cut으로 나눈 int tier.
  0이 가장 큰 font tier다.
- category: Document Parse category를 그대로 둔다.
- element_position_norm: 같은 element 안 line 위치를 0..1로 정규화한다.
- element_len_log: 같은 element 안 line 수의 log1p 값이다.
- pane_indent_tier: 035의 LLM pane 판정(2 pane)을 사용해 pane-local x indent를
  KDE valley cut으로 나눈 int tier다. 0이 pane 안에서 가장 왼쪽 indent다.
- numbering_depth: regex parser 내부 type은 숨기고 depth만 둔다. none은 -1,
  Part/Book/Unit은 0, Chapter/제N장은 1, 1.2는 2다.
- delta_font_tier, delta_pane_indent_tier, delta_numbering_depth: 같은 page/pane
  안에서 직전 candidate와의 차이다.
- same_numbering_parent: decimal numbering parent prefix가 같은지 여부다.
- y_gap_norm: 같은 page/pane 안에서 직전 candidate와의 y center 차이다.
- page_or_pane_break: 직전 candidate와 page 또는 pane이 달라 delta/gap이 끊긴 지점이다.

실행:
    uv run python experiments/050_generalized_minimal_feature_table_zvi.py

출력:
    experiments/outputs/050_generalized_minimal_feature_table_zvi/
"""

from __future__ import annotations

import csv
import json
import math
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from rapidfuzz import fuzz, process

from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks, title_has_letter
from pdfbooktree.utils.text_normalize import normalize_for_match, normalize_text

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "050_generalized_minimal_feature_table_zvi"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
LABELS_JSON = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
LINE_INPUT = (
    ROOT_DIR
    / "experiments"
    / "outputs"
    / "047_document_parse_output_formats_zvi"
    / "word_element_columns_lines.csv"
)
PANE_RESPONSE = (
    ROOT_DIR
    / "experiments"
    / "outputs"
    / "035_llm_pane_gated_indent_tier"
    / "zvi_bodie_investments"
    / "llm_pane_response.json"
)
TARGET_ID = "zvi_bodie_investments"

_LETTER = re.compile(r"[A-Za-z가-힣]")
_TRAILING_PAGE = re.compile(r"\s+\d+(?:\s*[-–]\s*\d+)?\s*$")
_DECIMAL = re.compile(r"^(\d+(?:\.\d+)+)\b")
_INTEGER = re.compile(r"^(?:\(?(\d{1,3})\)?[\).]?)\s+")
_ALPHA = re.compile(r"^(?:\(?([A-Za-z])\)?[\).])\s+")
_ROMAN = re.compile(r"^(?:\(?([IVXLCDM]+)\)?[\).])\s+", re.IGNORECASE)
_KOREAN_ORDER = re.compile(r"^([가-힣ㄱ-ㅎ])[\).]\s+")
_PART = re.compile(
    r"^(?:part|book|unit|section|부|편)\s*([IVXLCDM]+|\d+|[A-Z]|\|)?\b",
    re.IGNORECASE,
)
_CHAPTER = re.compile(
    r"^(?:chapter|chap\.?|ch\.?|제\s*\d+\s*장|\d+\s*장)\b",
    re.IGNORECASE,
)
_APPENDIX = re.compile(r"^(?:appendix|부록)\s*([A-Z]|\d+)?\b", re.IGNORECASE)


@dataclass
class LineRow:
    row_id: int
    text: str
    pdf_page: int
    element_id: str
    element_line_index: int
    column_index: int
    category: str
    html_max_font_size: float
    title_x: float
    page_width: float
    yc_norm: float


@dataclass
class NumberingInfo:
    numbering_depth: int
    numbering_parent_key: str
    numbering_token: str


@dataclass
class FeatureRow:
    row_id: int
    pdf_page: int
    pane_id: int
    reading_order: int
    text: str
    category: str
    font_tier: int
    element_position_norm: float
    element_len_log: float
    pane_indent_tier: int
    numbering_depth: int
    delta_font_tier: int | None
    delta_pane_indent_tier: int | None
    delta_numbering_depth: int | None
    same_numbering_parent: bool
    y_gap_norm: float | None
    page_or_pane_break: bool
    matched_bookmark_title: str | None
    matched_bookmark_level: int | None
    match_score: float | None


def safe_int(value: str | None, default: int = 0) -> int:
    try:
        return int(str(value))
    except Exception:
        return default


def safe_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(str(value))
    except Exception:
        return default


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


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


def normalize_candidate_text(text: str) -> str:
    text = normalize_text(text).replace("PART |", "PART I")
    return re.sub(r"\s+", " ", text).strip()


def has_letter(text: str) -> bool:
    return bool(_LETTER.search(text))


def strip_trailing_page(text: str) -> str:
    return _TRAILING_PAGE.sub("", text).strip()


def load_zvi_label() -> dict[str, Any]:
    labels = json.loads(LABELS_JSON.read_text(encoding="utf-8"))["labels"]
    for label in labels:
        if label["id"] == TARGET_ID:
            return label
    raise RuntimeError(f"{TARGET_ID} 라벨을 찾지 못했다.")


def load_lines() -> list[LineRow]:
    lines: list[LineRow] = []
    for row_id, row in enumerate(read_csv_dicts(LINE_INPUT)):
        text = normalize_candidate_text(row.get("text", ""))
        if not text or not has_letter(text):
            continue
        lines.append(
            LineRow(
                row_id=row_id,
                text=text,
                pdf_page=safe_int(row.get("pdf_page")),
                element_id=str(row.get("element_id", "")),
                element_line_index=safe_int(row.get("element_line_index")),
                column_index=safe_int(row.get("column_index")),
                category=str(row.get("category", "")),
                html_max_font_size=safe_float(row.get("html_max_font_size")),
                title_x=safe_float(row.get("title_x")),
                page_width=safe_float(row.get("page_width"), 1.0),
                yc_norm=safe_float(row.get("yc_norm")),
            )
        )
    return sorted(lines, key=reading_key)


def reading_key(line: LineRow) -> tuple[int, int, float, str, int]:
    pane_id = pane_id_for_line(line)
    return (line.pdf_page, pane_id, line.yc_norm, line.element_id, line.element_line_index)


def pane_count_from_035() -> int:
    response = json.loads(PANE_RESPONSE.read_text(encoding="utf-8"))
    pane_count = int(response.get("pane_count") or 1)
    return pane_count if pane_count in {1, 2} else 1


def pane_id_for_line(line: LineRow) -> int:
    # 035에서 Zvi는 2 pane으로 판정되었다. 이 결정은 feature가 아니라 전처리 metadata다.
    if not PANE_COUNT_IS_TWO:
        return 0
    return 0 if line.title_x < line.page_width / 2.0 else 1


def kde_valley_cuts(values: list[float], *, grid_size: int = 2048) -> list[float]:
    if len(values) < 3:
        return []
    arr = np.asarray(values, dtype=float)
    unique = np.unique(arr)
    if unique.size <= 1:
        return []
    std = float(np.std(arr, ddof=1))
    if std <= 0 or not math.isfinite(std):
        return []
    bandwidth = 1.06 * std * (len(arr) ** -0.2)
    if bandwidth <= 0 or not math.isfinite(bandwidth):
        return []
    pad = max(std * 0.5, 1.0)
    grid = np.linspace(float(arr.min()) - pad, float(arr.max()) + pad, grid_size)
    z = (grid[:, None] - arr[None, :]) / bandwidth
    density = np.exp(-0.5 * z * z).sum(axis=1)
    peak_idx = [
        index
        for index in range(1, len(density) - 1)
        if density[index - 1] < density[index] > density[index + 1]
    ]
    if len(peak_idx) < 2:
        return []
    valley_idx = [
        index
        for index in range(1, len(density) - 1)
        if density[index - 1] > density[index] < density[index + 1]
    ]
    peaks = sorted(float(grid[index]) for index in peak_idx)
    cuts = [
        float(grid[index])
        for index in valley_idx
        if peaks[0] < float(grid[index]) < peaks[-1]
    ]
    # 같은 두 peak 사이 valley가 여러 개 잡히면 가장 낮은 density 지점만 남긴다.
    deduped: list[float] = []
    for left, right in zip(peaks, peaks[1:]):
        candidates = [cut for cut in cuts if left < cut < right]
        if not candidates:
            continue
        best = min(
            candidates,
            key=lambda cut: float(density[int(np.argmin(np.abs(grid - cut)))]),
        )
        deduped.append(best)
    return sorted(set(round(cut, 6) for cut in deduped))


def assign_high_first_tier(value: float, cuts: list[float]) -> int:
    tier = 0
    for cut in sorted(cuts, reverse=True):
        if value >= cut:
            return tier
        tier += 1
    return tier


def assign_low_first_tier(value: float, cuts: list[float]) -> int:
    tier = 0
    for cut in sorted(cuts):
        if value < cut:
            return tier
        tier += 1
    return tier


def numbering_info(text: str) -> NumberingInfo:
    title = strip_trailing_page(normalize_candidate_text(text)).lstrip("•*-–— ")
    if not title:
        return NumberingInfo(-1, "", "")

    part = _PART.search(title)
    if part:
        return NumberingInfo(0, "part", part.group(0))

    chapter = _CHAPTER.search(title)
    if chapter:
        return NumberingInfo(1, "chapter", chapter.group(0))

    appendix = _APPENDIX.search(title)
    if appendix:
        return NumberingInfo(1, "appendix", appendix.group(0))

    decimal = _DECIMAL.search(title)
    if decimal:
        token = decimal.group(1)
        parts = token.split(".")
        parent = ".".join(parts[:-1]) if len(parts) > 1 else ""
        return NumberingInfo(len(parts), parent, token)

    integer = _INTEGER.search(title)
    if integer:
        return NumberingInfo(1, "ordered", integer.group(1))

    roman = _ROMAN.search(title)
    if roman:
        return NumberingInfo(1, "ordered", roman.group(1))

    alpha = _ALPHA.search(title)
    if alpha:
        return NumberingInfo(1, "ordered", alpha.group(1))

    korean = _KOREAN_ORDER.search(title)
    if korean:
        return NumberingInfo(1, "ordered", korean.group(1))

    return NumberingInfo(-1, "", "")


def element_stats(lines: list[LineRow]) -> dict[tuple[int, str], dict[int, tuple[float, float]]]:
    grouped: dict[tuple[int, str], list[LineRow]] = {}
    for line in lines:
        grouped.setdefault((line.pdf_page, line.element_id), []).append(line)

    out: dict[tuple[int, str], dict[int, tuple[float, float]]] = {}
    for key, members in grouped.items():
        ordered = sorted(
            members,
            key=lambda line: (pane_id_for_line(line), line.yc_norm, line.element_line_index),
        )
        denom = max(len(ordered) - 1, 1)
        length_log = round(math.log1p(len(ordered)), 6)
        out[key] = {
            line.row_id: (round(index / denom, 6), length_log)
            for index, line in enumerate(ordered)
        }
    return out


def font_tiers(lines: list[LineRow]) -> tuple[dict[int, int], list[float]]:
    values = [line.html_max_font_size for line in lines if line.html_max_font_size > 0]
    cuts = kde_valley_cuts(values)
    return {
        line.row_id: assign_high_first_tier(line.html_max_font_size, cuts)
        for line in lines
    }, cuts


def indent_tiers(lines: list[LineRow]) -> tuple[dict[int, int], dict[str, list[float]]]:
    by_group: dict[tuple[int, int], list[LineRow]] = {}
    for line in lines:
        by_group.setdefault((line.pdf_page, pane_id_for_line(line)), []).append(line)

    tiers: dict[int, int] = {}
    cuts_by_group: dict[str, list[float]] = {}
    for (pdf_page, pane_id), members in sorted(by_group.items()):
        values = [line.title_x for line in members]
        cuts = kde_valley_cuts(values)
        cuts_by_group[f"p{pdf_page}_pane{pane_id}"] = cuts
        for line in members:
            tiers[line.row_id] = assign_low_first_tier(line.title_x, cuts)
    return tiers, cuts_by_group


def load_bookmarks(pdf: Path) -> list[dict[str, Any]]:
    bookmarks = [
        bookmark
        for bookmark in extract_existing_bookmarks(pdf)
        if title_has_letter(str(bookmark.get("title") or ""))
    ]
    if not bookmarks:
        return []
    min_level = min(int(bookmark["level"]) for bookmark in bookmarks)
    rows: list[dict[str, Any]] = []
    for bookmark in bookmarks:
        rows.append(
            {
                "title": str(bookmark["title"]),
                "norm": normalize_for_match(str(bookmark["title"])),
                "level": int(bookmark["level"]) - min_level + 1,
            }
        )
    return rows


def attach_weak_labels(
    features: list[FeatureRow],
    bookmarks: list[dict[str, Any]],
) -> None:
    choices: list[str] = []
    by_norm: dict[str, FeatureRow] = {}
    for row in features:
        norm = normalize_for_match(row.text)
        if norm and norm not in by_norm:
            choices.append(norm)
            by_norm[norm] = row

    for bookmark in bookmarks:
        result = process.extractOne(
            bookmark["norm"], choices, scorer=fuzz.token_set_ratio, score_cutoff=88.0
        )
        if not result:
            continue
        feature = by_norm[result[0]]
        if feature.matched_bookmark_title is not None and (feature.match_score or 0) > result[1]:
            continue
        feature.matched_bookmark_title = bookmark["title"]
        feature.matched_bookmark_level = bookmark["level"]
        feature.match_score = round(float(result[1]), 4)


def build_feature_rows(lines: list[LineRow], bookmarks: list[dict[str, Any]]) -> tuple[list[FeatureRow], dict[str, Any]]:
    element_lookup = element_stats(lines)
    font_lookup, font_cuts = font_tiers(lines)
    indent_lookup, indent_cuts = indent_tiers(lines)
    numbering_lookup = {line.row_id: numbering_info(line.text) for line in lines}

    features: list[FeatureRow] = []
    previous: FeatureRow | None = None
    previous_numbering: NumberingInfo | None = None
    previous_yc_norm: float | None = None
    for order, line in enumerate(sorted(lines, key=reading_key)):
        pane_id = pane_id_for_line(line)
        element_position_norm, element_len_log = element_lookup[(line.pdf_page, line.element_id)][
            line.row_id
        ]
        numbering = numbering_lookup[line.row_id]
        page_or_pane_break = (
            previous is None
            or previous.pdf_page != line.pdf_page
            or previous.pane_id != pane_id
        )
        if previous is None or page_or_pane_break:
            delta_font = None
            delta_indent = None
            delta_numbering = None
            y_gap = None
            same_parent = False
        else:
            delta_font = font_lookup[line.row_id] - previous.font_tier
            delta_indent = indent_lookup[line.row_id] - previous.pane_indent_tier
            delta_numbering = numbering.numbering_depth - previous.numbering_depth
            y_gap = round(line.yc_norm - (previous_yc_norm or 0.0), 6)
            same_parent = bool(
                numbering.numbering_parent_key
                and previous_numbering is not None
                and numbering.numbering_parent_key == previous_numbering.numbering_parent_key
            )

        feature = FeatureRow(
            row_id=line.row_id,
            pdf_page=line.pdf_page,
            pane_id=pane_id,
            reading_order=order,
            text=line.text,
            category=line.category,
            font_tier=font_lookup[line.row_id],
            element_position_norm=element_position_norm,
            element_len_log=element_len_log,
            pane_indent_tier=indent_lookup[line.row_id],
            numbering_depth=numbering.numbering_depth,
            delta_font_tier=delta_font,
            delta_pane_indent_tier=delta_indent,
            delta_numbering_depth=delta_numbering,
            same_numbering_parent=same_parent,
            y_gap_norm=y_gap,
            page_or_pane_break=page_or_pane_break,
            matched_bookmark_title=None,
            matched_bookmark_level=None,
            match_score=None,
        )
        features.append(feature)
        previous = feature
        previous_numbering = numbering
        previous_yc_norm = line.yc_norm

    attach_weak_labels(features, bookmarks)
    debug = {
        "font_cuts": [round(value, 4) for value in font_cuts],
        "font_tier_distribution": dict(Counter(row.font_tier for row in features)),
        "indent_cuts_by_page_pane": {
            key: [round(value, 4) for value in value]
            for key, value in indent_cuts.items()
        },
        "pane_indent_tier_distribution": dict(
            Counter(row.pane_indent_tier for row in features)
        ),
        "numbering_depth_distribution": dict(
            Counter(row.numbering_depth for row in features)
        ),
        "category_distribution": dict(Counter(row.category for row in features)),
        "weak_label_matched_rows": sum(
            1 for row in features if row.matched_bookmark_level is not None
        ),
    }
    return features, debug


def feature_schema() -> dict[str, Any]:
    return {
        "features": {
            "font_tier": "int, KDE valley cut tier, 0이 가장 큰 font tier",
            "category": "categorical, Document Parse category 원본",
            "element_position_norm": "float, 같은 element 안 line 위치 0..1",
            "element_len_log": "float, log1p(element line count)",
            "pane_indent_tier": "int, LLM pane gate 이후 pane-local x indent KDE tier, 0이 가장 왼쪽",
            "numbering_depth": "int, none=-1, part=0, chapter/order=1, decimal depth=n",
            "delta_font_tier": "int or null, 같은 page/pane 직전 candidate와 font_tier 차이",
            "delta_pane_indent_tier": "int or null, 같은 page/pane 직전 candidate와 pane_indent_tier 차이",
            "delta_numbering_depth": "int or null, 같은 page/pane 직전 candidate와 numbering_depth 차이",
            "same_numbering_parent": "bool, decimal parent prefix가 직전 candidate와 같은지",
            "y_gap_norm": "float or null, 같은 page/pane 직전 candidate와 yc_norm 차이",
            "page_or_pane_break": "bool, delta/gap이 끊기는 page 또는 pane 전환 지점",
        },
        "label_columns": {
            "matched_bookmark_title": "feature가 아니라 weak label audit용 fuzzy matched bookmark title",
            "matched_bookmark_level": "feature가 아니라 weak label audit용 normalized bookmark level",
            "match_score": "feature가 아니라 weak label audit용 fuzzy score",
        },
    }


def build_finding(features: list[FeatureRow], debug: dict[str, Any], pane_count: int) -> str:
    return (
        f"Zvi 047 word_element_columns line {len(features)}개를 최소 feature table로 변환했다. "
        f"pane_count는 035 LLM pane gate 결과 {pane_count}를 재사용했다. "
        f"font_tier dist={debug['font_tier_distribution']}, "
        f"pane_indent_tier dist={debug['pane_indent_tier_distribution']}, "
        f"numbering_depth dist={debug['numbering_depth_distribution']}, "
        f"category dist={debug['category_distribution']}, "
        f"weak_label_matched_rows={debug['weak_label_matched_rows']}."
    )


def record_experiment(summary: dict[str, Any], label: dict[str, Any]) -> None:
    registry = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "047 Zvi Document Parse column-aware lines를 대상으로, 048/049의 overfit rule을 "
            "제거하고 font_tier/category/element_position/pane_indent/numbering_depth/"
            "prev delta로 구성된 일반화 가능한 최소 feature table을 만든다. pane 수는 "
            "035 LLM pane gate의 Zvi=2 pane 판정을 재사용한다."
        ),
        "inputs": [
            label["input_pdf"],
            str(LINE_INPUT.relative_to(ROOT_DIR)),
            str(PANE_RESPONSE.relative_to(ROOT_DIR)),
        ],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "data/native-pdf-indexed 기존 bookmark(golden 재활용, feature가 아닌 audit label)",
        "source_experiments": [
            "035_llm_pane_gated_indent_tier",
            "047_document_parse_output_formats_zvi",
        ],
        "finding": summary["finding"],
        "ran_at": summary["ran_at"],
    }
    registry["experiments"] = [
        experiment
        for experiment in registry["experiments"]
        if experiment.get("id") != EXPERIMENT_ID
    ]
    registry["experiments"].append(entry)
    EXPERIMENTS_JSON.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


PANE_COUNT_IS_TWO = pane_count_from_035() == 2


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    label = load_zvi_label()
    pdf = ROOT_DIR / label["input_pdf"]
    pane_count = 2 if PANE_COUNT_IS_TWO else 1
    lines = load_lines()
    bookmarks = load_bookmarks(pdf)
    features, debug = build_feature_rows(lines, bookmarks)

    feature_rows = []
    weak_label_rows = []
    label_keys = {"matched_bookmark_title", "matched_bookmark_level", "match_score"}
    for row in features:
        row_dict = asdict(row)
        feature_rows.append({key: value for key, value in row_dict.items() if key not in label_keys})
        if row.matched_bookmark_level is not None:
            weak_label_rows.append(
                {
                    "row_id": row.row_id,
                    "reading_order": row.reading_order,
                    "text": row.text,
                    "matched_bookmark_title": row.matched_bookmark_title,
                    "matched_bookmark_level": row.matched_bookmark_level,
                    "match_score": row.match_score,
                }
            )
    write_csv(OUTPUT_DIR / "feature_table.csv", feature_rows)
    write_csv(OUTPUT_DIR / "weak_label_audit.csv", weak_label_rows)
    (OUTPUT_DIR / "feature_schema.json").write_text(
        json.dumps(feature_schema(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "target_id": TARGET_ID,
        "input_lines": str(LINE_INPUT.relative_to(ROOT_DIR)),
        "pane_source": str(PANE_RESPONSE.relative_to(ROOT_DIR)),
        "pane_count": pane_count,
        "feature_count": len(feature_schema()["features"]),
        "row_count": len(features),
        "debug": debug,
        "finding": build_finding(features, debug, pane_count),
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_experiment(summary, label)

    print("\n=== exp 050: Generalized minimal feature table on Zvi ===")
    print(f"rows={len(features)} pane_count={pane_count}")
    print(f"font_tier={debug['font_tier_distribution']}")
    print(f"pane_indent_tier={debug['pane_indent_tier_distribution']}")
    print(f"numbering_depth={debug['numbering_depth_distribution']}")
    print(f"category={debug['category_distribution']}")
    print(f"weak_label_matched_rows={debug['weak_label_matched_rows']}")
    print(f"summary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()



