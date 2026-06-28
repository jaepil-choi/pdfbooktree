"""showcase 006: 추출한 목차의 tree hierarchy와 content가 정확한지 검증한다.

대상은 bookmark가 없는 scanned OCR 책(not-indexed)이다. 이런 책은 기존
bookmark가 없어 LLM이 목차를 처음부터 만들어 내므로, 다음 두 가지를 눈으로
확인할 수 있게 보여준다.

1. tree hierarchy: 추출한 항목의 level이 합리적으로 중첩되는지(1부터 시작,
   level 점프 없음, printed_page 단조 증가).
2. content: 추출한 각 항목의 제목이 실제 목차 PDF page text에 실재하는지
   (source grounding). offset이 clean하면 본문 page에서도 제목이 보이는지
   bonus spot-check를 한다.

모든 호출은 real data + live call이다. LLM은 Upstage Solar chat(solar-pro3)
텍스트 경로만 쓴다. synthetic/mock/stub 입력은 쓰지 않는다.

실행:
    uv run python showcase/006_verify_toc_tree_and_content.py
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

from pdfbooktree import (
    LlmRangeReviewConfig,
    LlmTocRangeReviewer,
    OffsetEstimationConfig,
    OffsetEstimationError,
    SizeAwareStagedTocExtractor,
    estimate_page_offset,
)
from pdfbooktree.models import PdfPageText, TocItem
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks
from pdfbooktree.pdf.text import extract_page_texts, extract_selected_page_texts
from pdfbooktree.toc.detect import detect_toc_pages
from pdfbooktree.toc.features import calculate_page_features
from pdfbooktree.utils.text_normalize import normalize_for_match

try:  # 콘솔에서 한글이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data" / "scanned-pdf-not-indexed"
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "006_verify_toc_tree_and_content"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "006_verify_toc_tree_and_content"

MAX_TOC_SEARCH_PAGES = 80
# 제목 token이 source/본문 text에 이 비율 이상 등장하면 grounded로 본다.
GROUNDING_TOKEN_THRESHOLD = 0.6
# grounding token 길이 필터(너무 짧은 token은 노이즈라 제외).
MIN_TOKEN_LEN = 2


def _case_id(path: Path) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", path.stem).strip("_")[:80]


def discover_not_indexed_cases() -> list[Path]:
    """not-indexed 디렉터리에서 bookmark가 정말 없는 PDF만 고른다."""

    cases: list[Path] = []
    for path in sorted(DATA_DIR.rglob("*.pdf")):
        try:
            if extract_existing_bookmarks(path):
                continue  # 혹시라도 bookmark가 있으면 대상에서 제외
        except Exception:  # noqa: BLE001 - 손상 PDF는 건너뛴다
            continue
        cases.append(path)
    return cases


def detect_and_extract(pdf_path: Path) -> dict[str, Any]:
    """detect → LLM range review → LLM item 추출을 live로 수행한다."""

    pages = extract_page_texts(pdf_path, max_pages=MAX_TOC_SEARCH_PAGES)
    with __import__("fitz").open(pdf_path) as document:
        total_pages = document.page_count

    features = calculate_page_features(pages, total_pages)
    detection = detect_toc_pages(features)

    reviewer = LlmTocRangeReviewer(LlmRangeReviewConfig())
    review = reviewer.review(pdf_path, detection, total_pages)
    toc_pages = review.pages if review.pages else detection.pages

    extractor = SizeAwareStagedTocExtractor()
    items = extractor.extract(pdf_path, toc_pages) if toc_pages else []

    return {
        "total_pages": total_pages,
        "detection_pages": detection.pages,
        "review_stage": review.stage,
        "review_pages": review.pages,
        "review_llm_calls": review.llm_calls,
        "toc_pages": toc_pages,
        "items": items,
    }


def analyze_hierarchy(items: list[TocItem]) -> dict[str, Any]:
    """level 중첩과 printed_page 순서로 tree hierarchy 건전성을 본다."""

    levels = [item.level for item in items]
    level_dist = dict(sorted(Counter(levels).items()))

    # level 점프: 직전 항목보다 2단계 이상 깊어지면 비정상 중첩이다.
    level_jumps: list[dict[str, Any]] = []
    prev_level: int | None = None
    for index, item in enumerate(items):
        if prev_level is not None and item.level - prev_level >= 2:
            level_jumps.append(
                {
                    "index": index,
                    "title": item.title,
                    "from": prev_level,
                    "to": item.level,
                }
            )
        prev_level = item.level

    # printed_page 단조성: 인쇄 page 번호가 있는 항목만 순서대로 비교한다.
    printed = [item.printed_page for item in items if item.printed_page is not None]
    inversions = sum(1 for a, b in zip(printed, printed[1:]) if b < a)
    monotonicity = 1.0 - inversions / max(len(printed) - 1, 1)

    return {
        "item_count": len(items),
        "level_distribution": level_dist,
        "max_depth": max(levels) if levels else 0,
        "starts_at_level_1": bool(levels) and min(levels) == 1,
        "level_jump_count": len(level_jumps),
        "level_jumps_sample": level_jumps[:5],
        "items_with_printed_page": len(printed),
        "printed_page_monotonicity": round(monotonicity, 4),
        "printed_page_inversions": inversions,
    }


def render_tree(items: list[TocItem]) -> list[str]:
    """level을 들여쓰기로 표현한 tree 전체를 만든다(자르지 않는다)."""

    lines: list[str] = []
    for item in items:
        indent = "    " * max(item.level - 1, 0)
        page = item.printed_page if item.printed_page is not None else "-"
        lines.append(f"{indent}[{page}] L{item.level} {item.title}")
    return lines


def _title_tokens(title: str) -> list[str]:
    normalized = normalize_for_match(title)
    return [tok for tok in normalized.split() if len(tok) >= MIN_TOKEN_LEN]


def _is_grounded(title: str, haystack_norm: str) -> bool:
    tokens = _title_tokens(title)
    if not tokens:
        return False
    hit = sum(1 for tok in tokens if tok in haystack_norm)
    return hit / len(tokens) >= GROUNDING_TOKEN_THRESHOLD


def verify_source_grounding(
    pdf_path: Path, items: list[TocItem], toc_pages: list[int]
) -> dict[str, Any]:
    """각 항목 제목이 자신의 source TOC page text에 실재하는지 본다(content 충실도)."""

    page_texts = extract_selected_page_texts(pdf_path, toc_pages)
    norm_by_page: dict[int, str] = {
        page.pdf_page: normalize_for_match(page.text) for page in page_texts
    }
    # source_pdf_page를 못 믿는 경우를 대비해 전체 TOC text도 합쳐 둔다.
    all_norm = " ".join(norm_by_page.values())

    grounded = 0
    ungrounded: list[dict[str, Any]] = []
    for item in items:
        page_norm = norm_by_page.get(item.source_pdf_page, "")
        if _is_grounded(item.title, page_norm) or _is_grounded(item.title, all_norm):
            grounded += 1
        else:
            ungrounded.append(
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
        "ungrounded_sample": ungrounded[:8],
    }


def verify_body_spotcheck(
    pdf_path: Path,
    items: list[TocItem],
    offset: int,
    total_pages: int,
    sample_size: int = 8,
) -> dict[str, Any]:
    """offset이 clean할 때, 표본 항목 제목이 본문 page 상단에 실재하는지 본다."""

    sampled = [item for item in items if item.printed_page is not None]
    if len(sampled) > sample_size:
        step = len(sampled) // sample_size
        sampled = sampled[::step][:sample_size]

    page_map: dict[int, int] = {}
    needed: set[int] = set()
    for item in sampled:
        estimated = item.printed_page + offset  # type: ignore[operator]
        if 1 <= estimated <= total_pages:
            page_map[id(item)] = estimated
            needed.add(estimated)

    page_texts: dict[int, PdfPageText] = {}
    if needed:
        for page in extract_selected_page_texts(pdf_path, sorted(needed)):
            page_texts[page.pdf_page] = page

    checks: list[dict[str, Any]] = []
    hit = 0
    for item in sampled:
        estimated = page_map.get(id(item))
        if estimated is None:
            continue
        # page 상단 1/3 정도(상위 12줄)에서 제목을 찾는다.
        top_lines = page_texts[estimated].lines[:12]
        top_norm = normalize_for_match(" ".join(top_lines))
        grounded = _is_grounded(item.title, top_norm)
        hit += int(grounded)
        checks.append(
            {
                "title": item.title,
                "printed_page": item.printed_page,
                "estimated_pdf_page": estimated,
                "found_on_page_top": grounded,
            }
        )

    return {
        "offset": offset,
        "checked": len(checks),
        "found": hit,
        "hit_rate": round(hit / len(checks), 4) if checks else 0.0,
        "checks": checks,
    }


def run_case(pdf_path: Path) -> dict[str, Any]:
    case_id = _case_id(pdf_path)
    record: dict[str, Any] = {
        "id": case_id,
        "input_pdf": str(pdf_path.relative_to(ROOT_DIR)),
    }

    extracted = detect_and_extract(pdf_path)
    items: list[TocItem] = extracted["items"]
    record.update(
        {
            "total_pages": extracted["total_pages"],
            "review_stage": extracted["review_stage"],
            "review_pages": extracted["review_pages"],
            "review_llm_calls": extracted["review_llm_calls"],
            "toc_pages": extracted["toc_pages"],
        }
    )

    if not items:
        record["status"] = "no_items"
        return record

    record["hierarchy"] = analyze_hierarchy(items)
    record["content_source_grounding"] = verify_source_grounding(
        pdf_path, items, extracted["toc_pages"]
    )

    # offset이 clean하면 본문 spot-check, fast-fail이면 정직하게 막혔다고 기록한다.
    try:
        offset_estimate = estimate_page_offset(pdf_path, OffsetEstimationConfig())
        record["offset"] = offset_estimate.offset
        record["body_spotcheck"] = verify_body_spotcheck(
            pdf_path, items, offset_estimate.offset, extracted["total_pages"]
        )
    except OffsetEstimationError as error:
        record["offset"] = None
        record["body_spotcheck"] = {
            "status": "blocked_offset_fast_fail",
            "error": str(error),
        }

    # tree 미리보기를 사람이 읽을 수 있게 별도 파일로도 남긴다.
    tree_lines = render_tree(items)
    tree_path = OUTPUT_DIR / f"{case_id}_tree.txt"
    tree_path.write_text("\n".join(tree_lines) + "\n", encoding="utf-8")
    record["tree_preview_file"] = str(tree_path.relative_to(ROOT_DIR))
    record["tree_preview"] = tree_lines[:20]
    record["status"] = "verified"
    return record


def build_finding(results: list[dict[str, Any]]) -> str:
    if not results:
        return (
            "data/scanned-pdf-not-indexed 아래에 bookmark 없는 PDF가 없어 검증할 "
            "입력이 없다(blocked)."
        )
    parts: list[str] = []
    for result in results:
        if result.get("status") == "no_items":
            parts.append(
                f"{result['id']}는 toc_pages={result.get('toc_pages')}에서 item을 "
                "추출하지 못했다."
            )
            continue
        hier = result["hierarchy"]
        ground = result["content_source_grounding"]
        body = result.get("body_spotcheck", {})
        body_str = (
            f"본문 spot-check {body.get('found')}/{body.get('checked')} "
            f"(offset={result.get('offset')})"
            if "checked" in body
            else f"본문 spot-check {body.get('status')}"
        )
        parts.append(
            f"{result['id']}: item {hier['item_count']}개, "
            f"level 분포 {hier['level_distribution']}, "
            f"level 점프 {hier['level_jump_count']}회, "
            f"printed_page 단조성 {hier['printed_page_monotonicity']}, "
            f"source grounding {ground['grounded']}/{ground['total']} "
            f"({ground['grounding_rate']}), {body_str}이다."
        )
    return " ".join(parts)


def record_showcase(results: list[dict[str, Any]], finding: str) -> None:
    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "bookmark 없는 scanned OCR 책에서 추출한 목차가 정확한 tree hierarchy"
            "(level 중첩, printed_page 순서)와 content(제목이 실제 목차/본문 page에 "
            "실재)를 갖는지 real data + live call로 검증한다. LLM은 solar-pro3 텍스트 "
            "경로만 쓴다."
        ),
        "inputs": [result["input_pdf"] for result in results],
        "outputs": "showcase/outputs/006_verify_toc_tree_and_content/result.json",
        "model": "solar-pro3",
        "finding": finding,
        "command": "uv run python showcase/006_verify_toc_tree_and_content.py",
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    replaced = False
    for index, existing in enumerate(data["showcases"]):
        if existing.get("id") == SHOWCASE_ID:
            data["showcases"][index] = entry
            replaced = True
            break
    if not replaced:
        data["showcases"].append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    if not DATA_DIR.exists():
        raise FileNotFoundError(DATA_DIR)

    load_dotenv(ROOT_DIR / ".env")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cases = discover_not_indexed_cases()
    results = [run_case(path) for path in cases]

    summary = {
        "purpose": (
            "not-indexed scanned OCR 책의 추출 목차에 대해 tree hierarchy와 content "
            "충실도를 검증한다."
        ),
        "source_experiments": [
            "016_llm_toc_range_3stage_fallback",
            "017_toc_font_size_cluster_hierarchy",
            "021_toc_staged_schema_then_extract",
        ],
        "item_extractor": "size_aware_staged_toc_extractor",
        "case_count": len(results),
        "results": results,
    }
    OUTPUT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    finding = build_finding(results)
    record_showcase(results, finding)

    print("=== 추출 목차 hierarchy/content 검증 (not-indexed scanned OCR) ===")
    if not results:
        print("- 입력 없음: not-indexed 디렉터리에 bookmark 없는 PDF가 없다(blocked).")
    for result in results:
        print(f"\n- {result['id']}: {result.get('status')}")
        print(
            f"    toc_pages={result.get('toc_pages')} "
            f"stage={result.get('review_stage')}"
        )
        if result.get("status") != "verified":
            continue
        hier = result["hierarchy"]
        ground = result["content_source_grounding"]
        body = result.get("body_spotcheck", {})
        print(
            f"    hierarchy: items={hier['item_count']} "
            f"levels={hier['level_distribution']} "
            f"jumps={hier['level_jump_count']} "
            f"mono={hier['printed_page_monotonicity']}"
        )
        print(
            f"    content: source grounding "
            f"{ground['grounded']}/{ground['total']} ({ground['grounding_rate']})"
        )
        if "checked" in body:
            print(
                f"    body spot-check: {body['found']}/{body['checked']} "
                f"found (offset={body['offset']})"
            )
        else:
            print(f"    body spot-check: {body.get('status')}")
        print("    tree preview:")
        for line in result["tree_preview"][:12]:
            print(f"      {line}")


if __name__ == "__main__":
    main()
