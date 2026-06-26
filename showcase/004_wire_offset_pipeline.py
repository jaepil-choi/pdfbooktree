"""showcase 004: Processor에 연결된 offset → alignment → ranges 흐름을 real data로 보여준다.

runtime `Processor`는 bookmark가 있는 PDF를 skip하므로, data/ 아래에서 bookmark가
없는 실제 PDF만 골라 `Processor.run()`을 live 호출한다. 파이프라인은
`estimate_page_offset` → heading alignment → content range까지 연결되어 있고,
offset이 clean하지 않으면 `OffsetEstimationError`를 그대로 전파한다(fallback 없음).

이 showcase는 그 예외도 정직하게 기록한다. synthetic/mock/stub 입력은 쓰지 않는다.

실행:
    uv run python showcase/004_wire_offset_pipeline.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pdfbooktree import OffsetEstimationError, ProcessingConfig, Processor
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks

try:  # 콘솔에서 한글이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "004_wire_offset_pipeline"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "004_wire_offset_pipeline"


def _case_id(path: Path) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", path.stem).strip("_")[:80]


def discover_bookmark_free_cases() -> list[dict[str, Any]]:
    """data/ 아래에서 bookmark가 없는 PDF만 runtime 입력 후보로 고른다.

    runtime Processor는 bookmark가 있으면 skip하므로, offset 파이프라인을 실제로
    타는 PDF는 bookmark가 없는 것들이다.
    """

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
    """단일 bookmark-free PDF에 Processor.run()을 live 호출한다."""

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
    config = ProcessingConfig(write_intermediates=True)
    try:
        result = Processor(pdf_path, case_output_dir, config).run()
    except OffsetEstimationError as error:
        # 기본 정책상 offset이 clean하지 않으면 파이프라인이 중단된다. 정직하게 기록.
        record["status"] = "offset_fast_failed"
        record["error"] = str(error)
        return record

    record["status"] = result.status
    record["toc_pages"] = result.toc_pages
    record["confidence_offset"] = result.confidence_summary.offset
    record["confidence_alignment"] = result.confidence_summary.alignment
    record["warnings"] = result.warnings

    offset_path = case_output_dir / "page_offset.json"
    ranges_path = case_output_dir / "ranges.json"
    aligned_path = case_output_dir / "toc_aligned.json"
    if offset_path.exists():
        offset_payload = json.loads(offset_path.read_text(encoding="utf-8"))
        record["offset"] = offset_payload.get("offset")
    if aligned_path.exists():
        aligned_payload = json.loads(aligned_path.read_text(encoding="utf-8"))
        record["aligned_item_count"] = len(aligned_payload)
        record["matched_item_count"] = sum(
            1
            for item in aligned_payload
            if item.get("method") == "offset_plus_heading_match_scaffold"
        )
    if ranges_path.exists():
        ranges_payload = json.loads(ranges_path.read_text(encoding="utf-8"))
        record["content_range_count"] = len(ranges_payload)
        record["content_range_sample"] = ranges_payload[:5]
    return record


def build_finding(results: list[dict[str, Any]]) -> str:
    if not results:
        return (
            "data/ 아래에 bookmark 없는 PDF가 없어 runtime offset 파이프라인을 "
            "보여줄 입력이 없다(blocked). bookmark 없는 실제 PDF가 필요하다."
        )
    parts: list[str] = []
    for result in results:
        status = result["status"]
        if status == "offset_fast_failed":
            parts.append(f"{result['id']}는 offset fast-fail({result['error']}).")
        elif status == "open_error":
            parts.append(f"{result['id']}는 PDF 열기 실패({result['error']}).")
        else:
            parts.append(
                f"{result['id']}는 status={status}, offset={result.get('offset')}, "
                f"toc_pages={result.get('toc_pages')}, "
                f"aligned={result.get('aligned_item_count')}"
                f"(matched {result.get('matched_item_count')}), "
                f"content_range={result.get('content_range_count')}, "
                f"conf(offset={result.get('confidence_offset')}, "
                f"alignment={result.get('confidence_alignment')})이다."
            )
    return " ".join(parts)


def record_showcase(results: list[dict[str, Any]], finding: str) -> None:
    """showcase.json에 이번 실행 기록을 추가한다(같은 id는 교체)."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "runtime Processor가 bookmark 없는 실제 PDF에서 estimate_page_offset → "
            "heading alignment → content range까지 연결되어 동작함을 보여준다. "
            "offset이 clean하지 않으면 OffsetEstimationError를 전파한다(fallback 없음)."
        ),
        "inputs": [result["input_pdf"] for result in results],
        "outputs": "showcase/outputs/004_wire_offset_pipeline/result.json",
        "finding": finding,
        "command": "uv run python showcase/004_wire_offset_pipeline.py",
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

    cases = discover_bookmark_free_cases()
    results = [run_case(case) for case in cases]
    summary = {
        "purpose": (
            "Processor.run()을 bookmark 없는 실제 PDF에 live 호출해 offset → "
            "alignment → ranges 연결이 동작함을 보여준다."
        ),
        "source_experiment": "015_header_footer_page_offset",
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

    print("=== offset 파이프라인 (real data, bookmark 없는 PDF) ===")
    if not results:
        print("- 입력 없음: bookmark 없는 PDF가 data/ 아래에 없다(blocked).")
    for result in results:
        print(f"- {result['id']}: {result['status']}")
        if result["status"] not in {"offset_fast_failed", "open_error"}:
            print(
                f"    offset={result.get('offset')} "
                f"toc_pages={result.get('toc_pages')} "
                f"aligned={result.get('aligned_item_count')} "
                f"matched={result.get('matched_item_count')} "
                f"ranges={result.get('content_range_count')}"
            )
        else:
            print(f"    {result.get('error')}")


if __name__ == "__main__":
    main()
