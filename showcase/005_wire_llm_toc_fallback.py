"""showcase 005: use_llm=True인 Processor의 LLM TOC fallback을 real data로 보여준다.

wired Processor는 use_llm=True일 때
1) `LlmTocRangeReviewer`로 TOC page range를 3단계 fallback 보정하고,
2) 결정적 regex 파서가 0개를 뽑으면 `LlmTocExtractor`로 목차 item을 채운다.

runtime Processor는 bookmark가 있는 PDF를 skip하므로, data/ 아래에서 bookmark가
없는 실제 PDF만 골라 `Processor.run()`을 live 호출한다. LLM은 Upstage Solar chat
(solar-pro3) 텍스트 경로만 쓴다. synthetic/mock/stub 입력은 쓰지 않는다.

offset이 clean하지 않으면 기존 정책대로 OffsetEstimationError를 전파하며, 그 경우도
정직하게 기록한다.

실행:
    uv run python showcase/005_wire_llm_toc_fallback.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from pdfbooktree import OffsetEstimationError, ProcessingConfig, Processor
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks

try:  # 콘솔에서 한글이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "005_wire_llm_toc_fallback"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "005_wire_llm_toc_fallback"


def _case_id(path: Path) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", path.stem).strip("_")[:80]


def discover_bookmark_free_cases() -> list[dict[str, Any]]:
    """data/ 아래에서 bookmark가 없는 PDF만 runtime 입력 후보로 고른다."""

    cases: list[dict[str, Any]] = []
    for path in sorted(DATA_DIR.rglob("*.pdf")):
        try:
            bookmarks = extract_existing_bookmarks(path)
        except Exception as error:  # noqa: BLE001 - PDF 손상 등은 건너뛰고 기록만
            cases.append({"id": _case_id(path), "path": path, "open_error": str(error)})
            continue
        if bookmarks:
            continue  # bookmark 있는 PDF는 runtime에서 skip되므로 제외
        cases.append({"id": _case_id(path), "path": path})
    return cases


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    """단일 bookmark-free PDF에 use_llm=True Processor.run()을 live 호출한다."""

    pdf_path: Path = case["path"]
    record: dict[str, Any] = {
        "id": case["id"],
        "input_pdf": str(pdf_path.relative_to(ROOT_DIR)),
    }
    if "open_error" in case:
        record["status"] = "open_error"
        record["error"] = case["open_error"]
        return record

    case_output_dir = OUTPUT_DIR / case["id"]
    config = ProcessingConfig(use_llm=True, write_intermediates=True)
    try:
        result = Processor(pdf_path, case_output_dir, config).run()
    except OffsetEstimationError as error:
        record["status"] = "offset_fast_failed"
        record["error"] = str(error)
        # offset 전에 LLM range review는 이미 돌아 intermediate가 남는다.
        _attach_range_review(record, case_output_dir)
        return record

    record["status"] = result.status
    record["toc_pages"] = result.toc_pages
    record["confidence_offset"] = result.confidence_summary.offset
    record["confidence_alignment"] = result.confidence_summary.alignment
    record["warnings"] = result.warnings

    _attach_range_review(record, case_output_dir)

    raw_path = case_output_dir / "toc_raw.json"
    offset_path = case_output_dir / "page_offset.json"
    ranges_path = case_output_dir / "ranges.json"
    if raw_path.exists():
        raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
        record["toc_item_count"] = len(raw_payload)
        record["toc_item_sample"] = [item.get("title") for item in raw_payload[:5]]
    if offset_path.exists():
        record["offset"] = json.loads(offset_path.read_text(encoding="utf-8")).get(
            "offset"
        )
    if ranges_path.exists():
        ranges_payload = json.loads(ranges_path.read_text(encoding="utf-8"))
        record["content_range_count"] = len(ranges_payload)
    return record


def _attach_range_review(record: dict[str, Any], case_output_dir: Path) -> None:
    review_path = case_output_dir / "toc_range_review.json"
    if not review_path.exists():
        return
    review = json.loads(review_path.read_text(encoding="utf-8"))
    record["range_review_stage"] = review.get("stage")
    record["range_review_pages"] = review.get("pages")
    record["range_review_llm_calls"] = review.get("llm_calls")


def build_finding(results: list[dict[str, Any]]) -> str:
    if not results:
        return (
            "data/ 아래에 bookmark 없는 PDF가 없어 use_llm 파이프라인을 보여줄 "
            "입력이 없다(blocked)."
        )
    parts: list[str] = []
    for result in results:
        status = result["status"]
        if status == "offset_fast_failed":
            parts.append(
                f"{result['id']}는 offset fast-fail이지만 LLM range review는 "
                f"stage={result.get('range_review_stage')} "
                f"pages={result.get('range_review_pages')} "
                f"(calls={result.get('range_review_llm_calls')})로 동작했다."
            )
        elif status == "open_error":
            parts.append(f"{result['id']}는 PDF 열기 실패({result['error']}).")
        else:
            parts.append(
                f"{result['id']}는 status={status}, "
                f"range review stage={result.get('range_review_stage')} "
                f"pages={result.get('range_review_pages')} "
                f"(calls={result.get('range_review_llm_calls')}), "
                f"toc_pages={result.get('toc_pages')}, "
                f"toc_item={result.get('toc_item_count')}, "
                f"offset={result.get('offset')}, "
                f"content_range={result.get('content_range_count')}이다."
            )
    return " ".join(parts)


def record_showcase(results: list[dict[str, Any]], finding: str) -> None:
    """showcase.json에 이번 실행 기록을 추가한다(같은 id는 교체)."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "use_llm=True인 runtime Processor가 bookmark 없는 실제 PDF에서 "
            "LlmTocRangeReviewer로 TOC range를 3단계 fallback 보정하고, 결정적 "
            "regex 파서가 0개면 LlmTocExtractor로 목차 item을 채움을 보여준다. "
            "LLM은 solar-pro3 텍스트 경로만 쓴다."
        ),
        "inputs": [result["input_pdf"] for result in results],
        "outputs": "showcase/outputs/005_wire_llm_toc_fallback/result.json",
        "model": "solar-pro3",
        "finding": finding,
        "command": "uv run python showcase/005_wire_llm_toc_fallback.py",
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    data["showcases"] = [s for s in data["showcases"] if s.get("id") != SHOWCASE_ID]
    data["showcases"].append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    if not DATA_DIR.exists():
        raise FileNotFoundError(DATA_DIR)

    load_dotenv(ROOT_DIR / ".env")
    cases = discover_bookmark_free_cases()
    results = [run_case(case) for case in cases]
    summary = {
        "purpose": (
            "use_llm=True Processor.run()을 bookmark 없는 실제 PDF에 live 호출해 "
            "LLM range review + item fallback이 동작함을 보여준다."
        ),
        "source_experiment": "016_llm_toc_range_3stage_fallback",
        "case_count": len(results),
        "results": results,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    finding = build_finding(results)
    record_showcase(results, finding)

    print("=== use_llm TOC fallback (real data, bookmark 없는 PDF) ===")
    if not results:
        print("- 입력 없음: bookmark 없는 PDF가 data/ 아래에 없다(blocked).")
    for result in results:
        print(f"- {result['id']}: {result['status']}")
        print(
            f"    range_review: stage={result.get('range_review_stage')} "
            f"pages={result.get('range_review_pages')} "
            f"calls={result.get('range_review_llm_calls')}"
        )
        if result["status"] not in {"offset_fast_failed", "open_error"}:
            print(
                f"    toc_pages={result.get('toc_pages')} "
                f"toc_item={result.get('toc_item_count')} "
                f"offset={result.get('offset')} "
                f"ranges={result.get('content_range_count')}"
            )


if __name__ == "__main__":
    main()
