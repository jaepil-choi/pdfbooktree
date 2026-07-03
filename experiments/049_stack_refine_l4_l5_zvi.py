"""experiment 049: Zvi TOC의 L4/L5를 sequence stack으로 다시 나눈다.

048의 full_feature_fusion은 category/element/column/html font/numbering을 결합해
Zvi 계층 성능을 크게 올렸지만, L5를 거의 전부 L4로 예측했다. 이 실험은 새 API 호출
없이 048의 feature_lines.csv를 재사용해, 화면 feature가 아니라 목차 sequence stack으로
L4 부모 항목과 L5 topic 항목을 분리할 수 있는지 검증한다.

비교 arm
- full_feature_048: 048 summary의 full_feature_fusion 지표를 baseline으로 인용한다.
- stack_refine_l5: L3 section 아래 L4 parent를 만나면 뒤따르는 slash topic을 L5로 내린다.
- segment_stack_pruned: slash container 줄, 반복 Contents header, 너무 generic한 table
  fragment를 줄인 뒤 같은 stack refinement를 적용한다.

실행:
    uv run python experiments/049_stack_refine_l4_l5_zvi.py

출력:
    experiments/outputs/049_stack_refine_l4_l5_zvi/
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
INPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "048_parse_html_feature_hierarchy"
INPUT_ITEMS = INPUT_DIR / "feature_lines.csv"
INPUT_SUMMARY = INPUT_DIR / "summary.json"
LABELS_PATH = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "049_stack_refine_l4_l5_zvi"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "049_stack_refine_l4_l5_zvi"
TARGET_ID = "zvi_bodie_investments"

_DECIMAL_SECTION = re.compile(r"^\d+\.\d+\b")
_CHAPTER = re.compile(r"^(Chapter|Chapter:)\s*\d*", re.IGNORECASE)
_PART = re.compile(r"^PART\b", re.IGNORECASE)
GENERIC_TITLES = {
    "assets",
    "bonds",
    "companies",
    "contents",
    "dure",
    "funds",
    "indexes",
    "markets",
    "options",
    "pools",
    "record",
    "securities",
}


@dataclass
class Item:
    arm: str
    source_item_id: int
    title: str
    raw_text: str
    pdf_page: int
    printed_page: int | None
    predicted_level: int
    category: str
    html_max_font_size: str
    source_row_ids: str
    rule: str


def safe_int(value: str | None, default: int = 0) -> int:
    try:
        return int(str(value))
    except Exception:
        return default


def optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value))
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


def normalize_title(text: str) -> str:
    text = normalize_text(text).replace("PART |", "PART I")
    return re.sub(r"\s+", " ", text).strip()


def load_zvi_label() -> dict[str, Any]:
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))["labels"]
    for label in labels:
        if label["id"] == TARGET_ID:
            return label
    raise RuntimeError(f"{TARGET_ID} 라벨을 찾지 못했다.")


def load_full_feature_items() -> list[Item]:
    rows = read_csv_dicts(INPUT_ITEMS)
    items: list[Item] = []
    for row in rows:
        if row.get("arm") != "full_feature_fusion":
            continue
        items.append(
            Item(
                arm="full_feature_fusion",
                source_item_id=safe_int(row.get("item_id")),
                title=normalize_title(row.get("title", "")),
                raw_text=normalize_title(row.get("raw_text", "")),
                pdf_page=safe_int(row.get("pdf_page")),
                printed_page=optional_int(row.get("printed_page")),
                predicted_level=safe_int(row.get("predicted_level"), 1),
                category=str(row.get("category", "")),
                html_max_font_size=str(row.get("html_max_font_size", "")),
                source_row_ids=str(row.get("source_row_ids", "")),
                rule=str(row.get("rule", "")),
            )
        )
    return sorted(items, key=lambda item: item.source_item_id)


def copy_item(item: Item, *, arm: str, level: int | None = None, rule_suffix: str = "") -> Item:
    new_item = Item(**asdict(item))
    new_item.arm = arm
    if level is not None:
        new_item.predicted_level = level
    if rule_suffix:
        new_item.rule = f"{new_item.rule}+{rule_suffix}"
    return new_item


def is_major_reset(item: Item) -> bool:
    return item.predicted_level <= 3 or bool(
        _DECIMAL_SECTION.search(item.title)
        or _CHAPTER.search(item.title)
        or _PART.search(item.title)
    )


def is_l4_parent_candidate(item: Item) -> bool:
    if item.predicted_level != 4:
        return False
    if "slash" in item.rule:
        return False
    if len(normalize_for_match(item.title)) < 8:
        return False
    return True


def is_slash_topic(item: Item) -> bool:
    return "slash_feature_child" in item.rule or "slash_line" in item.rule


def stack_refine(items: list[Item], arm: str, *, prune: bool) -> list[Item]:
    refined: list[Item] = []
    active_l4_parent = False
    last_major_level = 1
    for item in items:
        if prune and should_drop_item(item):
            continue

        level = item.predicted_level
        suffix = "stack_keep"
        if is_major_reset(item):
            last_major_level = min(item.predicted_level, 3)
            active_l4_parent = False
            if _CHAPTER.search(item.title):
                level = 2
                suffix = "chapter_fix"
            elif item.predicted_level <= 3:
                suffix = "major_reset"
        elif is_l4_parent_candidate(item) and last_major_level >= 3:
            level = 4
            active_l4_parent = True
            suffix = "l4_parent"
        elif is_slash_topic(item) and active_l4_parent:
            level = 5
            suffix = "slash_under_l4_parent"
        elif is_slash_topic(item) and last_major_level >= 3:
            level = 4
            suffix = "slash_under_l3"
        else:
            suffix = "fallback"

        refined.append(copy_item(item, arm=arm, level=level, rule_suffix=suffix))
    return refined


def should_drop_item(item: Item) -> bool:
    norm = normalize_for_match(item.title)
    if item.title.lower() == "contents" and item.pdf_page > 7:
        return True
    if item.category == "table" and norm in GENERIC_TITLES:
        return True
    if "slash_line" in item.rule and "/" in item.title:
        # 048에서 slash line 자체와 slash segment를 모두 item으로 만들었기 때문에
        # line container는 후보에서 제외하고 segment item만 남긴다.
        return True
    if norm in GENERIC_TITLES and item.predicted_level <= 2:
        return True
    return False


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
            }
        )
    return out


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


def evaluate_items(
    arm: str, items: list[Item], bookmarks: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    choices: list[str] = []
    index_by_norm: dict[str, int] = {}
    for index, item in enumerate(items):
        norm = normalize_for_match(item.title)
        if norm and norm not in index_by_norm:
            choices.append(norm)
            index_by_norm[norm] = index

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
        gt = str(bookmark["level"])
        pred = str(item.predicted_level)
        by_level_hit[gt] += 1
        confusion.setdefault(gt, Counter())[pred] += 1
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

    confusion_rows = [
        {
            "arm": arm,
            "gt_level": gt_level,
            "predicted_level": predicted_level,
            "count": count,
        }
        for gt_level, row in sorted(confusion.items(), key=lambda pair: int(pair[0]))
        for predicted_level, count in sorted(row.items(), key=lambda pair: int(pair[0]))
    ]
    errors = [
        match
        for match in matches
        if int(match["bookmark_level"]) != int(match["predicted_level"])
    ][:100]
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
            for level, count in sorted(Counter(item.predicted_level for item in items).items())
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


def load_048_full_metric() -> dict[str, Any]:
    summary = json.loads(INPUT_SUMMARY.read_text(encoding="utf-8"))
    for metric in summary["metrics"]:
        if metric["arm"] == "full_feature_fusion":
            baseline = dict(metric)
            baseline["arm"] = "full_feature_048"
            return baseline
    raise RuntimeError("048 summary에서 full_feature_fusion 지표를 찾지 못했다.")


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
            "048 full_feature_fusion이 Zvi TOC에서 L5를 거의 전부 L4로 예측한 문제를 "
            "분리해, 048 feature_lines.csv를 재사용한 sequence stack refinement로 "
            "L4 parent와 L5 slash topic을 구분할 수 있는지 검증한다."
        ),
        "inputs": [label["input_pdf"], str(INPUT_ITEMS.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "data/native-pdf-indexed 기존 bookmark(golden 재활용, 수기 라벨 아님)",
        "models": ["document-parse"],
        "source_experiment": "048_parse_html_feature_hierarchy",
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
    base_items = load_full_feature_items()
    bookmarks = load_bookmarks(pdf)

    arms = {
        "stack_refine_l5": stack_refine(base_items, "stack_refine_l5", prune=False),
        "segment_stack_pruned": stack_refine(base_items, "segment_stack_pruned", prune=True),
    }
    metrics = [load_048_full_metric()]
    all_items: list[dict[str, Any]] = []
    all_matches: list[dict[str, Any]] = []
    all_confusion: list[dict[str, Any]] = []
    all_errors: list[dict[str, Any]] = []
    for arm, items in arms.items():
        metric, matches, confusion, errors = evaluate_items(arm, items, bookmarks)
        metrics.append(metric)
        all_items.extend(asdict(item) for item in items)
        all_matches.extend(matches)
        all_confusion.extend(confusion)
        all_errors.extend(errors)

    write_csv(OUTPUT_DIR / "refined_items.csv", all_items)
    write_csv(OUTPUT_DIR / "matched_items.csv", all_matches)
    write_csv(OUTPUT_DIR / "level_confusion.csv", all_confusion)
    write_csv(OUTPUT_DIR / "error_examples.csv", all_errors)

    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "target_id": TARGET_ID,
        "input_items": str(INPUT_ITEMS.relative_to(ROOT_DIR)),
        "bookmark_ref_count": len(bookmarks),
        "metrics": metrics,
        "finding": build_finding(metrics),
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    record_experiment(summary, label)

    print("\n=== exp 049: Stack refine L4/L5 on Zvi Bodie ===")
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
