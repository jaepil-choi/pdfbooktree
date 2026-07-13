"""experiment 048: Document Parse HTML feature로 Zvi TOC 계층을 다시 추정한다.

047은 Document Parse의 ``output_formats=["text", "html", "markdown"]`` 결과에서
category, element boundary, word box, column split, html font-size가 모두 살아 있음을
확인했다. 이 실험은 새 API 호출 없이 047 산출물을 재사용해, 각 feature 조합이 Zvi
목차 계층 weakref 평가를 얼마나 개선하는지 분리한다.

비교 arm
- baseline_046_parse_geometry: 046의 Zvi parse_geometry 결과를 그대로 인용한다.
- word_columns_numbering_only: 047 column-aware word line에 번호/문자 패턴만 적용한다.
- word_columns_html_font: numbering_only에 html font-size/category 신호를 추가한다.
- full_feature_fusion: element/column 순서, PART/Chapter 결합, 줄 continuation, slash
  하위 항목 분할, sequence smoothing을 함께 적용한다.

실행:
    uv run python experiments/048_parse_html_feature_hierarchy.py

출력:
    experiments/outputs/048_parse_html_feature_hierarchy/
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks, title_has_letter
from pdfbooktree.utils.text_normalize import normalize_for_match, normalize_text

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


ROOT_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "047_document_parse_output_formats_zvi"
BASELINE_046 = ROOT_DIR / "experiments" / "outputs" / "046_parse_geometry_toc_hierarchy" / "summary.json"
LABELS_PATH = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "048_parse_html_feature_hierarchy"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "048_parse_html_feature_hierarchy"
TARGET_ID = "zvi_bodie_investments"

LINE_INPUT = INPUT_DIR / "word_element_columns_lines.csv"
ELEMENT_INPUT = INPUT_DIR / "elements.csv"

_LETTER = re.compile(r"[A-Za-z가-힣]")
_DIGIT = re.compile(r"\d+")
_LAST_PAGE = re.compile(r"\s+(\d+)(?:\s*[-–]\s*\d+)?\s*$")
_LAST_PAGE_RANGE = re.compile(r"\s+\d+(?:\s*[-–]\s*\d+)?\s*$")
_DECIMAL_SECTION = re.compile(r"^\d+\.\d+\b")
_PART = re.compile(r"^PART\s+([IVXLCDM]+|I|\|)\b", re.IGNORECASE)
_CHAPTER = re.compile(r"^Chapter\s+\d+\b", re.IGNORECASE)
_TOP_SECTION_WORDS = {
    "cover",
    "investments",
    "about the authors",
    "brief contents",
    "contents",
    "distinctive features",
    "supplements",
    "acknowledgments",
    "references to cfa problems",
    "glossary",
    "name index",
    "subject index",
    "notation, formulas",
}


@dataclass
class TocLine:
    row_id: int
    pdf_page: int
    element_id: str
    element_line_index: int
    column_index: int
    category: str
    html_max_font_size: float | None
    height: float | None
    title_x: float | None
    yc_norm: float | None
    text: str


@dataclass
class CandidateItem:
    arm: str
    item_id: int
    title: str
    raw_text: str
    pdf_page: int
    printed_page: int | None
    predicted_level: int
    category: str
    html_max_font_size: float | None
    source_row_ids: str
    rule: str


def safe_int(value: str | None, default: int = 0) -> int:
    try:
        return int(str(value))
    except Exception:
        return default


def safe_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


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


def load_zvi_label() -> dict[str, Any]:
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))["labels"]
    for label in labels:
        if label["id"] == TARGET_ID:
            return label
    raise RuntimeError(f"{TARGET_ID} 라벨을 찾지 못했다.")


def normalize_ocr_text(text: str) -> str:
    text = normalize_text(text)
    text = text.replace("PART |", "PART I").replace("Part |", "PART I")
    text = text.replace(" / ", " / ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def has_letter(text: str) -> bool:
    return bool(_LETTER.search(text))


def last_printed_page(text: str) -> int | None:
    match = _LAST_PAGE.search(text)
    if not match:
        return None
    return int(match.group(1))


def strip_printed_page(text: str) -> str:
    return _LAST_PAGE_RANGE.sub("", text).strip()


def is_noise_line(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if not has_letter(stripped):
        return True
    lowered = stripped.lower()
    if lowered in {"vi", "vii", "viii", "ix", "x"}:
        return True
    return False


def load_lines() -> list[TocLine]:
    rows = read_csv_dicts(LINE_INPUT)
    lines: list[TocLine] = []
    for index, row in enumerate(rows):
        text = normalize_ocr_text(row.get("text", ""))
        if is_noise_line(text):
            continue
        lines.append(
            TocLine(
                row_id=index,
                pdf_page=safe_int(row.get("pdf_page")),
                element_id=str(row.get("element_id", "")),
                element_line_index=safe_int(row.get("element_line_index")),
                column_index=safe_int(row.get("column_index")),
                category=str(row.get("category", "")),
                html_max_font_size=safe_float(row.get("html_max_font_size")),
                height=safe_float(row.get("height")),
                title_x=safe_float(row.get("title_x")),
                yc_norm=safe_float(row.get("yc_norm")),
                text=text,
            )
        )
    return sorted(
        lines,
        key=lambda line: (
            line.pdf_page,
            line.element_id,
            line.column_index,
            line.element_line_index,
            line.yc_norm or 0.0,
        ),
    )


def same_flow(left: TocLine, right: TocLine) -> bool:
    return (
        left.pdf_page == right.pdf_page
        and left.element_id == right.element_id
        and left.column_index == right.column_index
        and left.category == right.category
    )


def starts_major_marker(text: str) -> bool:
    return bool(_PART.search(text) or _CHAPTER.search(text) or _DECIMAL_SECTION.search(text))


def slash_segments(text: str) -> list[str]:
    if "/" not in text:
        return []
    pieces = [strip_printed_page(piece.strip(" /")) for piece in re.split(r"\s*/\s*", text)]
    return [piece for piece in pieces if has_letter(piece) and len(piece) >= 5]


def numbering_level(title: str, *, slash_child: bool = False) -> tuple[int, str]:
    clean = strip_printed_page(normalize_ocr_text(title))
    lowered = clean.lower()
    if lowered in _TOP_SECTION_WORDS or lowered.startswith("contents"):
        return 1, "top_section"
    if _PART.search(clean):
        return 1, "part"
    if lowered.startswith("preface"):
        return 1, "preface"
    if _CHAPTER.search(clean):
        return 2, "chapter"
    if _DECIMAL_SECTION.search(clean):
        return 3, "decimal_section"
    if lowered.startswith("end of chapter material"):
        return 3, "end_material"
    if slash_child:
        return 4, "slash_child"
    if "/" in clean:
        return 4, "slash_line"
    if last_printed_page(title) is not None:
        return 2, "title_with_page"
    return 4, "unnumbered_child"


def html_font_level(line: TocLine, title: str, *, slash_child: bool = False) -> tuple[int, str]:
    pattern_level, pattern_rule = numbering_level(title, slash_child=slash_child)
    size = line.html_max_font_size or 0.0
    if pattern_rule in {"top_section", "part", "preface", "chapter", "decimal_section", "end_material"}:
        return pattern_level, pattern_rule
    if size >= 22.0:
        return 1, "font_ge_22"
    if size >= 20.0:
        return 2, "font_ge_20"
    if size >= 18.0:
        return 2, "font_ge_18"
    return pattern_level, pattern_rule


def full_feature_level(line: TocLine, title: str, *, slash_child: bool = False) -> tuple[int, str]:
    clean = strip_printed_page(normalize_ocr_text(title))
    pattern_level, pattern_rule = numbering_level(clean, slash_child=slash_child)
    size = line.html_max_font_size or 0.0
    if slash_child:
        # Zvi 상세 목차의 slash 분할 항목은 대부분 section 아래의 세부 topic이다.
        return 4 if size >= 16.0 else 5, "slash_feature_child"
    if pattern_rule in {"top_section", "part", "preface"}:
        return 1, pattern_rule
    if pattern_rule == "chapter":
        return 2, pattern_rule
    if pattern_rule in {"decimal_section", "end_material"}:
        return 3, pattern_rule
    if line.category == "table" and size >= 18.0:
        return 1, "table_major"
    if line.category == "heading1" or size >= 20.0:
        return 2, "heading_or_large_font"
    if "/" in clean:
        return 4, "slash_line"
    if line.category == "index" and last_printed_page(title) is not None:
        return 3, "index_title_with_page"
    if line.category == "index":
        return 4, "index_child"
    return pattern_level, pattern_rule


def make_candidate(
    arm: str,
    item_id: int,
    line: TocLine,
    title: str,
    raw_text: str,
    level: int,
    rule: str,
    row_ids: list[int],
) -> CandidateItem:
    return CandidateItem(
        arm=arm,
        item_id=item_id,
        title=strip_printed_page(normalize_ocr_text(title)),
        raw_text=raw_text,
        pdf_page=line.pdf_page,
        printed_page=last_printed_page(raw_text),
        predicted_level=level,
        category=line.category,
        html_max_font_size=line.html_max_font_size,
        source_row_ids=";".join(str(row_id) for row_id in row_ids),
        rule=rule,
    )


def build_simple_candidates(lines: list[TocLine], arm: str) -> list[CandidateItem]:
    items: list[CandidateItem] = []
    seen: set[tuple[str, int, int]] = set()
    for line in lines:
        title = strip_printed_page(line.text)
        if is_noise_line(title):
            continue
        if arm == "word_columns_numbering_only":
            level, rule = numbering_level(title)
        else:
            level, rule = html_font_level(line, title)
        key = (normalize_for_match(title), line.pdf_page, level)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        items.append(make_candidate(arm, len(items), line, title, line.text, level, rule, [line.row_id]))
    return items


def build_full_feature_candidates(lines: list[TocLine]) -> list[CandidateItem]:
    items: list[CandidateItem] = []
    seen: set[tuple[str, int, int]] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        raw = line.text
        title = strip_printed_page(raw)
        row_ids = [line.row_id]
        consumed = 1

        if _PART.search(raw) and index + 1 < len(lines) and same_flow(line, lines[index + 1]):
            next_line = lines[index + 1]
            next_title = strip_printed_page(next_line.text)
            if next_title and not _PART.search(next_title):
                title = f"{title}: {next_title}"
                raw = f"{raw} {next_line.text}"
                row_ids.append(next_line.row_id)
                consumed = 2
        elif _CHAPTER.search(raw) and index + 1 < len(lines) and same_flow(line, lines[index + 1]):
            next_line = lines[index + 1]
            next_title = strip_printed_page(next_line.text)
            if next_title and not starts_major_marker(next_title):
                title = f"{title}: {next_title}"
                raw = f"{raw} {next_line.text}"
                row_ids.append(next_line.row_id)
                consumed = 2
        elif (
            last_printed_page(raw) is None
            and index + 1 < len(lines)
            and same_flow(line, lines[index + 1])
            and last_printed_page(lines[index + 1].text) is not None
            and not starts_major_marker(lines[index + 1].text)
            and "/" not in raw
        ):
            next_line = lines[index + 1]
            title = f"{title} {strip_printed_page(next_line.text)}"
            raw = f"{raw} {next_line.text}"
            row_ids.append(next_line.row_id)
            consumed = 2

        level, rule = full_feature_level(line, title)
        key = (normalize_for_match(title), line.pdf_page, level)
        if key[0] and key not in seen and not is_noise_line(title):
            seen.add(key)
            items.append(make_candidate("full_feature_fusion", len(items), line, title, raw, level, rule, row_ids))

        for segment in slash_segments(raw):
            seg_level, seg_rule = full_feature_level(line, segment, slash_child=True)
            seg_key = (normalize_for_match(segment), line.pdf_page, seg_level)
            if seg_key[0] and seg_key not in seen:
                seen.add(seg_key)
                items.append(
                    make_candidate(
                        "full_feature_fusion",
                        len(items),
                        line,
                        segment,
                        raw,
                        seg_level,
                        seg_rule,
                        row_ids,
                    )
                )
        index += consumed

    return smooth_full_feature_levels(items)


def smooth_full_feature_levels(items: list[CandidateItem]) -> list[CandidateItem]:
    smoothed: list[CandidateItem] = []
    last_chapter_level = 2
    for item in items:
        new_item = CandidateItem(**asdict(item))
        title = new_item.title
        if _CHAPTER.search(title):
            last_chapter_level = 2
        if _DECIMAL_SECTION.search(title):
            new_item.predicted_level = max(last_chapter_level + 1, 3)
            new_item.rule += "+smooth_decimal"
        if new_item.rule.startswith("slash") and smoothed:
            prev_level = smoothed[-1].predicted_level
            new_item.predicted_level = max(prev_level + 1, 4) if prev_level <= 3 else 4
            new_item.rule += "+smooth_slash"
        smoothed.append(new_item)
    return smoothed


def load_bookmarks(pdf: Path) -> list[dict[str, Any]]:
    bookmarks = [
        bookmark
        for bookmark in extract_existing_bookmarks(pdf)
        if title_has_letter(str(bookmark.get("title") or ""))
    ]
    if not bookmarks:
        return []
    min_level = min(int(bookmark["level"]) for bookmark in bookmarks)
    out: list[dict[str, Any]] = []
    for bookmark in bookmarks:
        out.append(
            {
                "title": str(bookmark["title"]),
                "norm": normalize_for_match(str(bookmark["title"])),
                "level": int(bookmark["level"]) - min_level + 1,
                "order": int(bookmark.get("order") or len(out)),
                "page": bookmark.get("page"),
            }
        )
    return out


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


def evaluate_items(
    arm: str, items: list[CandidateItem], bookmarks: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    choices: list[str] = []
    index_by_norm: dict[str, int] = {}
    for index, item in enumerate(items):
        norm = normalize_for_match(item.title)
        if norm and norm not in index_by_norm:
            index_by_norm[norm] = index
            choices.append(norm)

    matches: list[dict[str, Any]] = []
    by_level_total = Counter(str(bookmark["level"]) for bookmark in bookmarks)
    by_level_hit: Counter[str] = Counter()
    confusion: dict[str, Counter[str]] = {}
    for bookmark in bookmarks:
        result = process.extractOne(
            bookmark["norm"], choices, scorer=fuzz.token_set_ratio, score_cutoff=88.0
        )
        if not result:
            continue
        item = items[index_by_norm[result[0]]]
        by_level_hit[str(bookmark["level"])] += 1
        confusion.setdefault(str(bookmark["level"]), Counter())[str(item.predicted_level)] += 1
        matches.append(
            {
                "arm": arm,
                "bookmark_title": bookmark["title"],
                "bookmark_level": bookmark["level"],
                "bookmark_order": bookmark["order"],
                "matched_title": item.title,
                "predicted_level": item.predicted_level,
                "score": round(float(result[1]), 4),
                "pdf_page": item.pdf_page,
                "printed_page": item.printed_page,
                "category": item.category,
                "html_max_font_size": item.html_max_font_size,
                "rule": item.rule,
            }
        )

    abs_hits = sum(1 for match in matches if match["bookmark_level"] == match["predicted_level"])
    ordered = sorted(matches, key=lambda match: match["bookmark_order"])
    total_transitions = 0
    agree_transitions = 0
    for left, right in zip(ordered, ordered[1:]):
        total_transitions += 1
        if _sign(int(right["bookmark_level"]) - int(left["bookmark_level"])) == _sign(
            int(right["predicted_level"]) - int(left["predicted_level"])
        ):
            agree_transitions += 1

    errors = [
        match
        for match in matches
        if int(match["bookmark_level"]) != int(match["predicted_level"])
    ][:80]
    confusion_rows = [
        {
            "arm": arm,
            "gt_level": gt_level,
            "predicted_level": predicted_level,
            "count": count,
        }
        for gt_level, row in sorted(confusion.items(), key=lambda item: int(item[0]))
        for predicted_level, count in sorted(row.items(), key=lambda item: int(item[0]))
    ]
    metric = {
        "arm": arm,
        "item_count": len(items),
        "bookmark_ref_count": len(bookmarks),
        "matched": len(matches),
        "match_rate": round(len(matches) / len(bookmarks), 4) if bookmarks else 0.0,
        "abs_level_agreement": round(abs_hits / len(matches), 4) if matches else None,
        "rel_depth_agreement": (
            round(agree_transitions / total_transitions, 4) if total_transitions else None
        ),
        "level_distribution": {
            str(level): count
            for level, count in sorted(
                Counter(item.predicted_level for item in items).items()
            )
        },
        "by_gt_level": {
            level: {
                "matched": by_level_hit[level],
                "total": by_level_total[level],
                "recall": round(by_level_hit[level] / by_level_total[level], 4),
            }
            for level in sorted(by_level_total, key=lambda value: int(value))
        },
    }
    return metric, matches, confusion_rows, errors


def load_baseline_046() -> dict[str, Any]:
    summary = json.loads(BASELINE_046.read_text(encoding="utf-8"))
    for result in summary["results"]:
        if result["id"] != TARGET_ID:
            continue
        weakref = result["arms"]["parse_geometry"]["weakref"]
        return {
            "arm": "baseline_046_parse_geometry",
            "item_count": result["arms"]["parse_geometry"]["hierarchy"]["item_count"],
            "bookmark_ref_count": weakref["bookmark_letter_count"],
            "matched": weakref["matched"],
            "match_rate": weakref["match_rate"],
            "abs_level_agreement": weakref["abs_level_agreement"],
            "rel_depth_agreement": weakref["rel_depth_agreement"],
            "level_distribution": result["arms"]["parse_geometry"]["hierarchy"][
                "level_distribution"
            ],
        }
    raise RuntimeError("046 summary에서 Zvi 결과를 찾지 못했다.")


def font_category_stats(items: list[CandidateItem], matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matched_by_title = {
        (match["arm"], normalize_for_match(match["matched_title"]), int(match["predicted_level"])): match
        for match in matches
    }
    grouped: dict[tuple[str, str, str, int], Counter[str]] = {}
    for item in items:
        key = (
            item.arm,
            item.category,
            str(item.html_max_font_size),
            item.predicted_level,
        )
        matched = matched_by_title.get((item.arm, normalize_for_match(item.title), item.predicted_level))
        status = "matched_correct" if matched and matched["bookmark_level"] == item.predicted_level else (
            "matched_wrong" if matched else "unmatched"
        )
        grouped.setdefault(key, Counter())[status] += 1
    rows: list[dict[str, Any]] = []
    for (arm, category, font_size, predicted_level), counter in sorted(grouped.items()):
        rows.append(
            {
                "arm": arm,
                "category": category,
                "html_max_font_size": font_size,
                "predicted_level": predicted_level,
                "matched_correct": counter["matched_correct"],
                "matched_wrong": counter["matched_wrong"],
                "unmatched": counter["unmatched"],
                "total": sum(counter.values()),
            }
        )
    return rows


def build_finding(metrics: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for metric in metrics:
        parts.append(
            f"{metric['arm']}: items={metric['item_count']} "
            f"matched={metric['matched']}/{metric['bookmark_ref_count']} "
            f"match={metric['match_rate']} abs={metric['abs_level_agreement']} "
            f"rel={metric['rel_depth_agreement']} levels={metric['level_distribution']}"
        )
    return " || ".join(parts)


def record_experiment(summary: dict[str, Any], label: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "047에서 확인한 Document Parse html font-size, category, element boundary, "
            "word box column split, numbering pattern을 feature로 결합해 Zvi Bodie TOC "
            "항목의 level을 다시 추정한다. 새 API 호출 없이 047 산출물을 재사용하고, "
            "046 parse_geometry weakref 결과와 abs/rel hierarchy agreement를 비교한다."
        ),
        "inputs": [label["input_pdf"], str(LINE_INPUT.relative_to(ROOT_DIR)), str(ELEMENT_INPUT.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "data/native-pdf-indexed 기존 bookmark(golden 재활용, 수기 라벨 아님)",
        "models": ["document-parse"],
        "source_experiments": [
            "046_parse_geometry_toc_hierarchy",
            "047_document_parse_output_formats_zvi",
        ],
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
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    label = load_zvi_label()
    pdf = ROOT_DIR / label["input_pdf"]
    lines = load_lines()
    bookmarks = load_bookmarks(pdf)

    arms = {
        "word_columns_numbering_only": build_simple_candidates(lines, "word_columns_numbering_only"),
        "word_columns_html_font": build_simple_candidates(lines, "word_columns_html_font"),
        "full_feature_fusion": build_full_feature_candidates(lines),
    }

    all_items: list[CandidateItem] = []
    metrics = [load_baseline_046()]
    all_matches: list[dict[str, Any]] = []
    all_confusion: list[dict[str, Any]] = []
    all_errors: list[dict[str, Any]] = []
    for arm, items in arms.items():
        metric, matches, confusion, errors = evaluate_items(arm, items, bookmarks)
        metrics.append(metric)
        all_items.extend(items)
        all_matches.extend(matches)
        all_confusion.extend(confusion)
        all_errors.extend(errors)

    write_csv(OUTPUT_DIR / "feature_lines.csv", [asdict(item) for item in all_items])
    write_csv(OUTPUT_DIR / "matched_items.csv", all_matches)
    write_csv(OUTPUT_DIR / "level_confusion.csv", all_confusion)
    write_csv(OUTPUT_DIR / "error_examples.csv", all_errors)
    write_csv(OUTPUT_DIR / "font_category_level_stats.csv", font_category_stats(all_items, all_matches))

    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "target_id": TARGET_ID,
        "input_lines": str(LINE_INPUT.relative_to(ROOT_DIR)),
        "input_elements": str(ELEMENT_INPUT.relative_to(ROOT_DIR)),
        "bookmark_ref_count": len(bookmarks),
        "metrics": metrics,
        "finding": build_finding(metrics),
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    record_experiment(summary, label)

    print("\n=== exp 048: Parse HTML feature hierarchy on Zvi Bodie ===")
    for metric in metrics:
        print(
            f"- {metric['arm']}: items={metric['item_count']} "
            f"matched={metric['matched']}/{metric['bookmark_ref_count']} "
            f"match={metric['match_rate']} abs={metric['abs_level_agreement']} "
            f"rel={metric['rel_depth_agreement']} levels={metric['level_distribution']}"
        )
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
