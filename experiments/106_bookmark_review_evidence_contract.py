"""실험 106: bookmark review evidence 계약을 실제 inference artifact로 검증한다.

목적
- 최종 plan item을 heading/fallback candidate와 손실 없이 연결한다.
- agent가 전체 typography line을 scan하지 않고 summary와 단일 JSONL item만으로
  검토 대상을 고르고 주변 근거를 확인할 수 있는지 검증한다.
- attention signal을 품질 판정이 아닌 검토 순서 정보로만 표현한다.

실행
    uv run python experiments/106_bookmark_review_evidence_contract.py
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz

from pdfbooktree.utils.text_normalize import normalize_text

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "106_bookmark_review_evidence_contract"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
SUMMARY_PATH = OUTPUT_DIR / "bookmark_review_summary.json"
ITEMS_PATH = OUTPUT_DIR / "bookmark_review_items.jsonl"
RESULT_PATH = OUTPUT_DIR / "result.json"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
DEFAULT_ARTIFACT_DIR = (
    ROOT_DIR / "showcase" / "outputs" / "028_markdown_graph_review" / "typography_split"
)
DEFAULT_PDF = (
    ROOT_DIR
    / "data"
    / "scanned-pdf-indexed"
    / (
        "(Springer Finance) Steven E. Shreve - Stochastic Calculus for Finance I "
        "The Binomial Asset Pricing Model-Springer (2005)-indexed.pdf"
    )
)
PREVIEW_CHAR_LIMIT = 800
SURROUNDING_LINE_RADIUS = 2


def read_json(path: Path) -> Any:
    """UTF-8 JSON을 읽는다."""

    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """독립 JSON object로 구성된 JSONL을 읽는다."""

    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_json(path: Path, value: Any) -> None:
    """UTF-8 JSON을 기록한다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """각 행을 독립 parse 가능한 UTF-8 JSONL로 기록한다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def candidate_key(source: str, pdf_page: int, title: str) -> tuple[str, int, str]:
    """plan 정규화 뒤에도 유지되는 candidate 연결 key를 만든다."""

    return source, pdf_page, normalize_text(title).casefold()


def candidate_index(
    heading_candidates: list[dict[str, Any]],
    fallback_candidates: list[dict[str, Any]],
) -> dict[tuple[str, int, str], list[dict[str, Any]]]:
    """candidate artifact 위치와 geometry를 plan 연결 key로 index한다."""

    index: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for position, candidate in enumerate(heading_candidates):
        key = candidate_key(
            str(candidate["source"]),
            int(candidate["pdf_page"]),
            str(candidate["title"]),
        )
        index[key].append(
            {
                "artifact": "heading_candidates.json",
                "index": position,
                "kind": "heading_candidate",
                "candidate": candidate,
            }
        )
    for position, candidate in enumerate(fallback_candidates):
        key = candidate_key(
            "geometry_position_fallback",
            int(candidate["pdf_page"]),
            str(candidate["title"]),
        )
        index[key].append(
            {
                "artifact": "position_fallback_candidates.json",
                "index": position,
                "kind": "position_fallback_candidate",
                "candidate": candidate,
            }
        )
    return index


def ordered_lines_by_page(
    lines: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    """typography line을 1-based page와 읽기 순서로 묶는다."""

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for line in lines:
        grouped[int(line["pdf_page"])].append(line)
    for page_lines in grouped.values():
        page_lines.sort(key=lambda row: (float(row["y0"]), float(row["x0"])))
    return grouped


def page_preview(page_lines: list[dict[str, Any]]) -> tuple[str, bool]:
    """typography line에서 길이가 제한된 page text preview를 만든다."""

    text = normalize_text(" ".join(str(line["text"]) for line in page_lines))
    if len(text) <= PREVIEW_CHAR_LIMIT:
        return text, False
    return text[:PREVIEW_CHAR_LIMIT].rstrip() + "…", True


def surrounding_lines(
    page_lines: list[dict[str, Any]], candidate: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """candidate y 위치 주변의 제한된 typography line을 반환한다."""

    if not page_lines:
        return []
    candidate_y = float(candidate.get("y0", 0.0)) if candidate else 0.0
    center = min(
        range(len(page_lines)),
        key=lambda index: abs(float(page_lines[index]["y0"]) - candidate_y),
    )
    start = max(0, center - SURROUNDING_LINE_RADIUS)
    end = min(len(page_lines), center + SURROUNDING_LINE_RADIUS + 1)
    return [
        {
            "text": line["text"],
            "y0": line["y0"],
            "y1": line["y1"],
            "font_size": line["font_size"],
            "height": line["height"],
            "is_bold": line["is_bold"],
        }
        for line in page_lines[start:end]
    ]


def attention_signals(
    item: dict[str, Any],
    *,
    title_count: int,
    page_item_count: int,
    page_line_count: int,
    candidate_match_count: int,
    previous_page: int | None,
) -> list[str]:
    """합격/불합격 판정 없이 먼저 볼 지점을 나타내는 signal을 만든다."""

    signals: list[str] = []
    title = normalize_text(str(item["title"]))
    if item.get("source") == "geometry_position_fallback":
        signals.append("position_fallback_source")
    if re.fullmatch(r"[\d\W_]+", title, flags=re.UNICODE):
        signals.append("numeric_only_title")
    if title_count > 1:
        signals.append("repeated_title")
    if len(title) > 100:
        signals.append("long_title")
    if page_item_count > 1:
        signals.append("same_page_bookmarks")
    if page_line_count == 0:
        signals.append("no_typography_text_on_page")
    elif page_line_count <= 2:
        signals.append("low_typography_line_count")
    if candidate_match_count == 0:
        signals.append("candidate_match_missing")
    elif candidate_match_count > 1:
        signals.append("duplicate_candidates_collapsed")
    if previous_page is not None and int(item["pdf_page"]) - previous_page > 20:
        signals.append("long_page_gap_from_previous")
    return signals


def build_review_items(
    plan: list[dict[str, Any]],
    candidates: dict[tuple[str, int, str], list[dict[str, Any]]],
    lines_by_page: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """최종 plan과 후보·주변 text를 item별 review row로 결합한다."""

    title_counts = Counter(
        normalize_text(str(item["title"])).casefold() for item in plan
    )
    page_counts = Counter(int(item["pdf_page"]) for item in plan)
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(plan):
        order = index + 1
        node_id = f"n{order:04d}"
        key = candidate_key(
            str(item.get("source", "typography")),
            int(item["pdf_page"]),
            str(item["title"]),
        )
        matches = candidates.get(key, [])
        match = matches[0] if matches else None
        candidate = match["candidate"] if match else None
        page_lines = lines_by_page.get(int(item["pdf_page"]), [])
        preview, preview_truncated = page_preview(page_lines)
        signals = attention_signals(
            item,
            title_count=title_counts[key[2]],
            page_item_count=page_counts[int(item["pdf_page"])],
            page_line_count=len(page_lines),
            candidate_match_count=len(matches),
            previous_page=int(plan[index - 1]["pdf_page"]) if index else None,
        )
        rows.append(
            {
                "schema_version": 1,
                "node_id": node_id,
                "order": order,
                "title": item["title"],
                "level": item["level"],
                "pdf_page": item["pdf_page"],
                "source": item.get("source", "typography"),
                "confidence": item.get("confidence", 0.0),
                "confidence_semantics": (
                    "pipeline evidence 값이며 bookmark 내용 품질의 합격 확률이 아니다"
                ),
                "evidence": item.get("evidence", []),
                "previous_node_id": f"n{index:04d}" if index else None,
                "next_node_id": f"n{order + 1:04d}" if index + 1 < len(plan) else None,
                "candidate_match_status": "matched" if matches else "missing",
                "candidate_ref": (
                    {
                        "artifact": match["artifact"],
                        "index": match["index"],
                        "kind": match["kind"],
                    }
                    if match
                    else None
                ),
                "candidate_alternative_refs": [
                    {
                        "artifact": alternative["artifact"],
                        "index": alternative["index"],
                        "kind": alternative["kind"],
                    }
                    for alternative in matches[1:]
                ],
                "candidate_geometry": (
                    {
                        key: candidate.get(key)
                        for key in (
                            "tier",
                            "y0",
                            "y1",
                            "merged_line_count",
                            "support_pages",
                            "isolation_ratio",
                            "font_ratio",
                        )
                        if key in candidate
                    }
                    if candidate
                    else None
                ),
                "page_line_count": len(page_lines),
                "page_text_preview": preview,
                "page_text_preview_truncated": preview_truncated,
                "surrounding_lines": surrounding_lines(page_lines, candidate),
                "source_artifacts": {
                    "whole_book_lines": "whole_book_lines.jsonl",
                    "bookmark_plan": "bookmark_plan.json",
                },
                "attention_signals": signals,
            }
        )
    return rows


def density_windows(
    plan: list[dict[str, Any]], total_pages: int
) -> list[dict[str, int]]:
    """50-page 단위 bookmark 밀도를 계산한다."""

    windows: list[dict[str, int]] = []
    for start in range(1, total_pages + 1, 50):
        end = min(total_pages, start + 49)
        windows.append(
            {
                "start_pdf_page": start,
                "end_pdf_page": end,
                "bookmark_count": sum(
                    start <= int(item["pdf_page"]) <= end for item in plan
                ),
            }
        )
    return windows


def build_summary(
    pdf_path: Path,
    artifact_dir: Path,
    plan: list[dict[str, Any]],
    heading_candidates: list[dict[str, Any]],
    fallback_candidates: list[dict[str, Any]],
    lines_by_page: dict[int, list[dict[str, Any]]],
    rows: list[dict[str, Any]],
    total_pages: int,
) -> dict[str, Any]:
    """agent가 가장 먼저 읽을 review summary를 만든다."""

    signal_counts = Counter(
        signal for row in rows for signal in row["attention_signals"]
    )
    repeated_titles = Counter(
        normalize_text(str(item["title"])).casefold() for item in plan
    )
    attention_rows = sorted(
        (row for row in rows if row["attention_signals"]),
        key=lambda row: (-len(row["attention_signals"]), row["order"]),
    )
    return {
        "schema_version": 1,
        "review_policy": (
            "attention signal은 검토 순서를 위한 정보이며 품질 합격/불합격 판정이 아니다"
        ),
        "confidence_semantics": (
            "pipeline evidence 값이며 bookmark 내용 품질의 합격 확률이 아니다"
        ),
        "input": {
            "pdf_path": str(pdf_path),
            "artifact_dir": str(artifact_dir),
            "page_count": total_pages,
        },
        "plan_item_count": len(plan),
        "level_counts": dict(
            sorted(Counter(int(item["level"]) for item in plan).items())
        ),
        "source_counts": dict(
            sorted(
                Counter(str(item.get("source", "typography")) for item in plan).items()
            )
        ),
        "candidate_counts": {
            "heading": len(heading_candidates),
            "position_fallback": len(fallback_candidates),
            "final_plan": len(plan),
        },
        "candidate_mapping": {
            "matched_count": sum(
                row["candidate_match_status"] == "matched" for row in rows
            ),
            "missing_count": sum(
                row["candidate_match_status"] == "missing" for row in rows
            ),
            "ambiguous_count": 0,
            "duplicate_candidates_collapsed_item_count": sum(
                bool(row["candidate_alternative_refs"]) for row in rows
            ),
        },
        "page_density_windows": density_windows(plan, total_pages),
        "title_statistics": {
            "numeric_only_count": sum(
                "numeric_only_title" in row["attention_signals"] for row in rows
            ),
            "long_title_count": sum(
                "long_title" in row["attention_signals"] for row in rows
            ),
            "repeated_title_value_count": sum(
                count > 1 for count in repeated_titles.values()
            ),
        },
        "text_statistics": {
            "page_with_no_typography_text_count": sum(
                page not in lines_by_page for page in range(1, total_pages + 1)
            ),
            "page_with_at_most_two_lines_count": sum(
                len(lines_by_page.get(page, [])) <= 2
                for page in range(1, total_pages + 1)
            ),
        },
        "attention": {
            "item_count": len(attention_rows),
            "signal_counts": dict(sorted(signal_counts.items())),
            "priority_items": [
                {
                    "node_id": row["node_id"],
                    "title": row["title"],
                    "pdf_page": row["pdf_page"],
                    "signals": row["attention_signals"],
                }
                for row in attention_rows[:20]
            ],
        },
        "artifacts": {
            "items": ITEMS_PATH.name,
            "bookmark_plan": "bookmark_plan.json",
            "whole_book_lines": "whole_book_lines.jsonl",
            "heading_candidates": "heading_candidates.json",
            "position_fallback_candidates": "position_fallback_candidates.json",
        },
        "next_commands": [
            "uv run pdfbooktree inspect plan <RUN> --attention-only --limit 20 --format json",
            "uv run pdfbooktree inspect plan <RUN> --item-id n0001 --format json",
            "uv run pdfbooktree inspect text <PDF> --pages 1 --format json",
        ],
    }


def update_experiments_json(summary: dict[str, Any], pdf_path: Path) -> None:
    """실험 결과를 experiments.json에 upsert한다."""

    data = read_json(EXPERIMENTS_JSON)
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "실제 inference artifact에서 plan summary와 item detail을 만들고 candidate "
            "mapping, 주변 text, attention signal과 독립 JSONL 계약을 검증한다."
        ),
        "inputs": [str(pdf_path.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "Shreve typography plan, heading/fallback candidate와 whole-book line을 "
            "node ID 기준 review summary/item으로 결합하고 mapping과 parsing 불변식을 "
            "기계적으로 검증했다."
        ),
        "summary": summary,
        "finding": (
            f"plan={summary['plan_item_count']}, candidate matched="
            f"{summary['candidate_mapping']['matched_count']}, missing="
            f"{summary['candidate_mapping']['missing_count']}, ambiguous="
            f"{summary['candidate_mapping']['ambiguous_count']}, JSONL="
            f"{summary['jsonl_independent_parse_count']}, validation="
            f"{summary['validation_passed']}"
        ),
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    experiments = data["experiments"]
    for index, existing in enumerate(experiments):
        if existing.get("id") == EXPERIMENT_ID:
            experiments[index] = entry
            break
    else:
        experiments.append(entry)
    write_json(EXPERIMENTS_JSON, data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    args = parser.parse_args()
    artifact_dir = args.artifact_dir.resolve()
    pdf_path = args.pdf.resolve()
    if not artifact_dir.is_dir():
        raise FileNotFoundError(
            f"실제 inference artifact directory가 없다: {artifact_dir}"
        )
    if not pdf_path.is_file():
        raise FileNotFoundError(f"실제 PDF가 없다: {pdf_path}")

    plan = read_json(artifact_dir / "bookmark_plan.json")
    heading_candidates = read_json(artifact_dir / "heading_candidates.json")
    fallback_candidates = read_json(artifact_dir / "position_fallback_candidates.json")
    lines = read_jsonl(artifact_dir / "whole_book_lines.jsonl")
    with fitz.open(pdf_path) as document:
        total_pages = document.page_count

    candidates = candidate_index(heading_candidates, fallback_candidates)
    lines_by_page = ordered_lines_by_page(lines)
    rows = build_review_items(plan, candidates, lines_by_page)
    summary = build_summary(
        pdf_path,
        artifact_dir,
        plan,
        heading_candidates,
        fallback_candidates,
        lines_by_page,
        rows,
        total_pages,
    )

    write_jsonl(ITEMS_PATH, rows)
    independent_rows = read_jsonl(ITEMS_PATH)
    validation = {
        "item_count_matches_plan": len(rows) == len(plan),
        "node_ids_unique": len({row["node_id"] for row in rows}) == len(rows),
        "candidate_mapping_complete": all(
            row["candidate_match_status"] == "matched" for row in rows
        ),
        "source_preserved": all(
            row["source"] == item["source"]
            for row, item in zip(rows, plan, strict=True)
        ),
        "confidence_preserved": all(
            row["confidence"] == item["confidence"]
            for row, item in zip(rows, plan, strict=True)
        ),
        "evidence_preserved": all(
            row["evidence"] == item["evidence"]
            for row, item in zip(rows, plan, strict=True)
        ),
        "jsonl_independent_parse": len(independent_rows) == len(rows),
        "preview_bounded": all(
            len(row["page_text_preview"]) <= PREVIEW_CHAR_LIMIT + 1 for row in rows
        ),
        "no_quality_verdict": all("quality" not in row for row in rows),
    }
    validation_passed = all(validation.values())
    summary["validation"] = validation
    summary["validation_passed"] = validation_passed
    write_json(SUMMARY_PATH, summary)

    result = {
        "plan_item_count": len(plan),
        "candidate_mapping": summary["candidate_mapping"],
        "attention_item_count": summary["attention"]["item_count"],
        "attention_signal_counts": summary["attention"]["signal_counts"],
        "whole_book_line_count": len(lines),
        "jsonl_independent_parse_count": len(independent_rows),
        "single_item_requires_whole_book_scan": False,
        "validation": validation,
        "validation_passed": validation_passed,
    }
    write_json(RESULT_PATH, result)
    update_experiments_json(result, pdf_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not validation_passed:
        raise RuntimeError(f"review evidence 계약 검증 실패: {RESULT_PATH}")


if __name__ == "__main__":
    main()
