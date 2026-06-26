"""showcase 003: estimate_page_offset public interface를 real data로 보여준다.

현재 data/ 아래 실제 PDF에 `estimate_page_offset`를 live 호출해 header/footer
page number로 printed-to-PDF offset을 추정한다. clean하지 않으면 fast-fail
(`OffsetEstimationError`)하며 fallback은 없다. 실패도 정직하게 기록한다.

synthetic/mock/stub 입력은 쓰지 않는다. 실제 PDF가 필요하다.

실행:
    uv run python showcase/003_page_offset_estimation.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pdfbooktree import OffsetEstimationError, estimate_page_offset
from pdfbooktree.utils.jsonio import to_jsonable

try:  # 콘솔에서 한글이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "003_page_offset_estimation"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "003_page_offset_estimation"


def discover_pdf_cases() -> list[dict[str, Any]]:
    """현재 data/ 아래 sample PDF를 showcase 입력으로 사용한다."""

    return [
        {
            "id": re.sub(r"[^0-9A-Za-z가-힣]+", "_", path.stem).strip("_")[:80],
            "path": path,
        }
        for path in sorted(DATA_DIR.rglob("*.pdf"))
    ]


def analyze_case(case: dict[str, Any]) -> dict[str, Any]:
    """단일 PDF에 estimate_page_offset를 live 호출한다."""

    pdf_path: Path = case["path"]
    record: dict[str, Any] = {
        "id": case["id"],
        "input_pdf": str(pdf_path.relative_to(ROOT_DIR)),
    }
    try:
        estimate = estimate_page_offset(pdf_path)
    except OffsetEstimationError as error:
        record["status"] = "fast_failed"
        record["offset"] = None
        record["error"] = str(error)
        return record

    head = estimate.evidence[0] if estimate.evidence else {}
    record["status"] = "estimated"
    record["offset"] = estimate.offset
    record["confidence"] = estimate.confidence
    record["best_band"] = head.get("best_band")
    record["modal_count"] = head.get("modal_count")
    record["dominance_ratio"] = head.get("dominance_ratio")
    record["max_consecutive_run"] = head.get("max_consecutive_run")
    record["consistent_page_count"] = head.get("consistent_page_count")
    record["printed_page_1_estimated_pdf_page"] = head.get(
        "printed_page_1_estimated_pdf_page"
    )
    record["evidence"] = estimate.evidence
    return record


def build_finding(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for result in results:
        if result["status"] != "estimated":
            parts.append(f"{result['id']}는 fast-fail({result['error']}).")
            continue
        parts.append(
            f"{result['id']}는 offset {result['offset']} "
            f"(band {result['best_band']}, modal_count {result['modal_count']}, "
            f"dominance {result['dominance_ratio']}, run {result['max_consecutive_run']}, "
            f"printed page 1 ≈ PDF page {result['printed_page_1_estimated_pdf_page']})이다."
        )
    return " ".join(parts)


def record_showcase(results: list[dict[str, Any]], finding: str) -> None:
    """showcase.json에 이번 실행 기록을 추가한다(같은 id는 교체)."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "estimate_page_offset public interface가 현재 data/ 아래 실제 PDF의 "
            "header/footer page number로 printed-to-PDF offset을 추정함을 보여준다. "
            "clean하지 않으면 fast-fail하며 fallback은 두지 않는다."
        ),
        "inputs": [result["input_pdf"] for result in results],
        "outputs": "showcase/outputs/003_page_offset_estimation/result.json",
        "finding": finding,
        "command": "uv run python showcase/003_page_offset_estimation.py",
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    data["showcases"] = [s for s in data["showcases"] if s.get("id") != SHOWCASE_ID]
    data["showcases"].append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    pdf_cases = discover_pdf_cases()
    if not pdf_cases:
        raise FileNotFoundError(DATA_DIR)

    results = [analyze_case(case) for case in pdf_cases]
    summary = {
        "purpose": (
            "estimate_page_offset를 현재 data/ 아래 실제 PDF에 live 호출해 "
            "header/footer page number 기반 offset 추정이 동작함을 보여준다."
        ),
        "source_experiment": "015_header_footer_page_offset",
        "case_count": len(results),
        "results": results,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(to_jsonable(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    finding = build_finding(results)
    record_showcase(results, finding)

    print("=== offset 추정 (real data) ===")
    for result in results:
        if result["status"] == "estimated":
            print(
                f"- {result['id']}: offset={result['offset']} "
                f"band={result['best_band']} modal={result['modal_count']} "
                f"dominance={result['dominance_ratio']} run={result['max_consecutive_run']}"
            )
        else:
            print(f"- {result['id']}: FAST-FAIL {result['error']}")


if __name__ == "__main__":
    main()
