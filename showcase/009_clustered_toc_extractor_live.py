"""showcase 009: 최신 clustered staged TOC extractor를 real data + live call로 검증한다.

experiment 029/030에서 채택한 전략(결정론 멀티피처 클러스터 + LLM 클러스터
순서/병합 + level marker 기반 항목 분리 + 제목 교정)이 src production extractor에
이식된 뒤, 기존 data/ PDF에서 실제로 작동하는지 보여준다.

검증은 synthetic/mock/stub 없이 수행한다. 수동 TOC range 라벨은 실제 data PDF의
목차 page 선택에만 사용하고, 항목 추출은 `SizeAwareStagedTocExtractor` public
interface와 Upstage solar-pro3 live call로 수행한다.

실행:
    uv run python showcase/009_clustered_toc_extractor_live.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from rapidfuzz import fuzz, process

from pdfbooktree import SizeAwareStagedTocExtractor
from pdfbooktree.models import TocItem
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks, title_has_letter
from pdfbooktree.pdf.text import extract_selected_page_texts
from pdfbooktree.utils.text_normalize import normalize_for_match

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


ROOT_DIR = Path(__file__).resolve().parents[1]
LABELS_PATH = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "009_clustered_toc_extractor_live"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "009_clustered_toc_extractor_live"

TARGET_IDS = [
    "john_hull",
    "shreve_binomial",
    "luenberger_investment_science",
    "algorithm_nine",
    "algorithms_to_live_by",
]

GROUNDING_TOKEN_THRESHOLD = 0.6
MIN_TOKEN_LEN = 2


def _case_id(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", text).strip("_")[:80]


def _contents_pages(label: dict[str, Any]) -> list[int]:
    pages: list[int] = []
    for segment in label.get("toc_segments") or []:
        if segment.get("kind") == "contents":
            pages.extend(range(segment["start_page"], segment["end_page"] + 1))
    return sorted(dict.fromkeys(pages or list(label["toc_pages"])))


def _normalize_bookmark_levels(bookmarks: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def weakref_metrics(
    items: list[TocItem], bookmarks: list[dict[str, Any]]
) -> dict[str, Any]:
    """기존 bookmark가 있는 책에서 title fuzzy matching으로 계층 품질을 본다."""

    reference = _normalize_bookmark_levels(bookmarks)
    if not reference or not items:
        return {"bookmark_letter_count": len(reference), "matched": 0}

    item_norms = [normalize_for_match(item.title) for item in items]
    index_by_norm: dict[str, int] = {}
    choices: list[str] = []
    for index, norm in enumerate(item_norms):
        if norm and norm not in index_by_norm:
            index_by_norm[norm] = index
            choices.append(norm)

    pairs: list[tuple[dict[str, Any], TocItem]] = []
    for bookmark in reference:
        bookmark_norm = normalize_for_match(bookmark["title"])
        if not bookmark_norm:
            continue
        match = process.extractOne(
            bookmark_norm,
            choices,
            scorer=fuzz.token_set_ratio,
            score_cutoff=88.0,
        )
        if match:
            pairs.append((bookmark, items[index_by_norm[match[0]]]))

    matched = len(pairs)
    abs_hits = sum(1 for bookmark, item in pairs if bookmark["level"] == item.level)
    ordered = sorted(pairs, key=lambda pair: pair[0]["order"])
    transitions = 0
    transition_hits = 0
    for (before_bookmark, before_item), (after_bookmark, after_item) in zip(
        ordered, ordered[1:]
    ):
        transitions += 1
        if _sign(after_bookmark["level"] - before_bookmark["level"]) == _sign(
            after_item.level - before_item.level
        ):
            transition_hits += 1

    return {
        "bookmark_letter_count": len(reference),
        "matched": matched,
        "match_rate": round(matched / len(reference), 4) if reference else 0.0,
        "abs_level_agreement": round(abs_hits / matched, 4) if matched else None,
        "rel_depth_agreement": (
            round(transition_hits / transitions, 4) if transitions else None
        ),
    }


def hierarchy_metrics(items: list[TocItem]) -> dict[str, Any]:
    """level 분포와 printed page 순서를 요약한다."""

    levels = [item.level for item in items]
    printed = [item.printed_page for item in items if item.printed_page is not None]
    inversions = sum(1 for before, after in zip(printed, printed[1:]) if after < before)
    monotonicity = 1.0 - inversions / max(len(printed) - 1, 1)
    jumps = []
    previous: int | None = None
    for index, item in enumerate(items):
        if previous is not None and item.level - previous >= 2:
            jumps.append(
                {
                    "index": index,
                    "title": item.title,
                    "from": previous,
                    "to": item.level,
                }
            )
        previous = item.level
    return {
        "item_count": len(items),
        "level_distribution": {str(k): v for k, v in sorted(Counter(levels).items())},
        "max_depth": max(levels) if levels else 0,
        "starts_at_level_1": bool(levels) and min(levels) == 1,
        "level_jump_count": len(jumps),
        "level_jumps_sample": jumps[:8],
        "items_with_printed_page": len(printed),
        "printed_page_monotonicity": round(monotonicity, 4),
        "printed_page_inversions": inversions,
    }


def _title_tokens(title: str) -> list[str]:
    return [
        token
        for token in normalize_for_match(title).split()
        if len(token) >= MIN_TOKEN_LEN
    ]


def _is_grounded(title: str, haystack_norm: str) -> bool:
    tokens = _title_tokens(title)
    if not tokens:
        return False
    hit = sum(1 for token in tokens if token in haystack_norm)
    return hit / len(tokens) >= GROUNDING_TOKEN_THRESHOLD


def source_grounding(
    pdf_path: Path, items: list[TocItem], toc_pages: list[int]
) -> dict[str, Any]:
    """추출 제목이 실제 TOC page text에 존재하는지 확인한다."""

    page_texts = extract_selected_page_texts(pdf_path, toc_pages)
    norm_by_page = {
        page.pdf_page: normalize_for_match(page.text) for page in page_texts
    }
    all_norm = " ".join(norm_by_page.values())

    grounded = 0
    misses: list[dict[str, Any]] = []
    for item in items:
        page_norm = norm_by_page.get(item.source_pdf_page, "")
        if _is_grounded(item.title, page_norm) or _is_grounded(item.title, all_norm):
            grounded += 1
        else:
            misses.append(
                {
                    "title": item.title,
                    "level": item.level,
                    "printed_page": item.printed_page,
                    "source_pdf_page": item.source_pdf_page,
                }
            )
    total = len(items)
    return {
        "grounded": grounded,
        "total": total,
        "grounding_rate": round(grounded / total, 4) if total else 0.0,
        "misses_sample": misses[:10],
    }


def render_tree(items: list[TocItem]) -> list[str]:
    lines: list[str] = []
    for item in items:
        indent = "    " * max(item.level - 1, 0)
        printed = item.printed_page if item.printed_page is not None else "-"
        lines.append(f"{indent}[{printed}] L{item.level} {item.title}")
    return lines


def load_targets() -> list[dict[str, Any]]:
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))["labels"]
    by_id = {label["id"]: label for label in labels}
    return [by_id[target_id] for target_id in TARGET_IDS if target_id in by_id]


def run_case(
    label: dict[str, Any], extractor: SizeAwareStagedTocExtractor
) -> dict[str, Any]:
    pdf_path = ROOT_DIR / label["input_pdf"]
    toc_pages = _contents_pages(label)
    record: dict[str, Any] = {
        "id": label["id"],
        "input_pdf": label["input_pdf"],
        "toc_pages": toc_pages,
    }
    if not pdf_path.exists():
        record["status"] = "missing_pdf"
        return record

    bookmarks = extract_existing_bookmarks(pdf_path)
    items = extractor.extract(pdf_path, toc_pages)
    tree_lines = render_tree(items)
    tree_path = OUTPUT_DIR / f"{_case_id(label['id'])}_tree.txt"
    tree_path.write_text("\n".join(tree_lines) + "\n", encoding="utf-8")

    record.update(
        {
            "status": "verified" if items else "no_items",
            "existing_bookmark_count": len(bookmarks),
            "hierarchy": hierarchy_metrics(items),
            "source_grounding": source_grounding(pdf_path, items, toc_pages),
            "weakref": weakref_metrics(items, bookmarks) if bookmarks else None,
            "tree_file": str(tree_path.relative_to(ROOT_DIR)),
            "tree_preview": tree_lines[:24],
        }
    )
    return record


def build_finding(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for result in results:
        if result.get("status") == "missing_pdf":
            parts.append(f"{result['id']}: missing_pdf")
            continue
        hierarchy = result["hierarchy"]
        grounding = result["source_grounding"]
        weakref = result.get("weakref")
        weakref_text = ""
        if weakref:
            weakref_text = (
                f", weakref match {weakref.get('matched')}/"
                f"{weakref.get('bookmark_letter_count')} "
                f"rel={weakref.get('rel_depth_agreement')} "
                f"abs={weakref.get('abs_level_agreement')}"
            )
        parts.append(
            f"{result['id']}: items={hierarchy['item_count']}, "
            f"levels={hierarchy['level_distribution']}, "
            f"jumps={hierarchy['level_jump_count']}, "
            f"printed_mono={hierarchy['printed_page_monotonicity']}, "
            f"source_grounding={grounding['grounded']}/{grounding['total']} "
            f"({grounding['grounding_rate']}){weakref_text}"
        )
    return " | ".join(parts)


def record_showcase(results: list[dict[str, Any]], finding: str) -> None:
    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "experiment 029/030에서 채택한 clustered staged TOC extractor가 기존 data/ "
            "PDF에서 실제 live call로 작동하는지 검증한다. 수동 TOC range로 실제 목차 "
            "page를 입력하고, 최신 production extractor가 계층/항목/제목을 추출한 뒤 "
            "indexed PDF는 bookmark weak reference와 비교한다."
        ),
        "inputs": [result["input_pdf"] for result in results],
        "outputs": str(OUTPUT_PATH.relative_to(ROOT_DIR)),
        "labels": str(LABELS_PATH.relative_to(ROOT_DIR)),
        "model": "solar-pro3",
        "finding": finding,
        "command": "uv run python showcase/009_clustered_toc_extractor_live.py",
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    showcases = data["showcases"]
    for index, existing in enumerate(showcases):
        if existing.get("id") == SHOWCASE_ID:
            showcases[index] = entry
            break
    else:
        showcases.append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    load_dotenv(ROOT_DIR / ".env")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    extractor = SizeAwareStagedTocExtractor()
    results: list[dict[str, Any]] = []
    for label in load_targets():
        result = run_case(label, extractor)
        results.append(result)
        # live showcase는 LLM 호출량이 있어 중간 실패/timeout에도 근거가 남도록
        # 케이스 단위로 summary를 갱신한다.
        partial_finding = build_finding(results)
        OUTPUT_PATH.write_text(
            json.dumps(
                {
                    "purpose": "최신 clustered staged extractor live 검증",
                    "source_experiments": [
                        "029_toc_cluster_llm_order",
                        "030_toc_pipeline_integration",
                    ],
                    "case_count": len(results),
                    "results": results,
                    "finding": partial_finding,
                    "partial": len(results) < len(load_targets()),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    finding = build_finding(results)
    summary = {
        "purpose": "최신 clustered staged extractor live 검증",
        "source_experiments": [
            "029_toc_cluster_llm_order",
            "030_toc_pipeline_integration",
        ],
        "case_count": len(results),
        "results": results,
        "finding": finding,
        "partial": False,
    }
    OUTPUT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    record_showcase(results, finding)

    print("=== showcase 009: clustered staged extractor live ===")
    for result in results:
        print(f"\n- {result['id']}: {result.get('status')}")
        if result.get("status") == "missing_pdf":
            print("    missing input")
            continue
        hierarchy = result["hierarchy"]
        grounding = result["source_grounding"]
        print(f"    toc_pages={result['toc_pages']}")
        print(
            f"    hierarchy: items={hierarchy['item_count']} "
            f"levels={hierarchy['level_distribution']} "
            f"jumps={hierarchy['level_jump_count']} "
            f"mono={hierarchy['printed_page_monotonicity']}"
        )
        print(
            f"    source grounding: {grounding['grounded']}/{grounding['total']} "
            f"({grounding['grounding_rate']})"
        )
        if result.get("weakref"):
            weakref = result["weakref"]
            print(
                f"    weakref: matched={weakref.get('matched')}/"
                f"{weakref.get('bookmark_letter_count')} "
                f"rel={weakref.get('rel_depth_agreement')} "
                f"abs={weakref.get('abs_level_agreement')}"
            )
        print("    tree preview:")
        for line in result["tree_preview"][:12]:
            print(f"      {line}")
    print(f"\nfinding: {finding}")


if __name__ == "__main__":
    main()
