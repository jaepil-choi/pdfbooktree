"""showcase 023: inspect_compare_plans()로 실제 두 infer 결과를 비교한다.

Phase 5 첫 증분에서 추가한 `compare_bookmark_plans()`/`inspect_compare_plans()`를
실제 책 한 권의 서로 다른 두 config 실행 결과로 검증한다. 두 실행 모두
`infer` CLI가 내부적으로 쓰는 것과 같은 `analyze_pdf()`/`infer_bookmarks()`/
`write_inference_artifacts()`를 호출해 실제 `bookmark_plan.json` artifact
두 개를 만들고, `inspect_compare_plans()`가 그 두 파일을 읽어 비교한다.

두 config:
  1. 기본 TypographyConfig(position fallback 켜짐)
  2. `position_fallback_enabled=False` - body-tier font에 흡수돼 font 골격만
     으로는 못 찾는 heading을 rescue하지 않는 config다. 이 차이가 실제로
     `removed`(fallback config에만 없는 항목) 항목을 만드는지 확인한다.

책은 showcase 022와 같은 `실습과_그림으로_배우는_리눅스_구조`(305쪽)를 쓴다 -
scanned/OCR 책이라 position fallback이 실제로 여러 heading을 찾아낸 것으로
이미 알려져 있어(showcase 022: predicted=171), 두 config 차이가 눈에 보일
가능성이 높다.

실행:
    uv run python showcase/023_bookmark_plan_compare.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pdfbooktree import (
    TypographyConfig,
    analyze_pdf,
    inspect_compare_plans,
    infer_bookmarks,
    write_inference_artifacts,
)

try:  # 콘솔에서 한글이 깨지지 않게 한다.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
INPUT_PDF = (
    ROOT_DIR
    / "data"
    / "300STUDY"
    / "a_books"
    / "textbook"
    / "실습과_그림으로_배우는_리눅스_구조_다케우치_사토루.pdf"
)
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "023_bookmark_plan_compare"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "023_bookmark_plan_compare"


def run_infer(output_dir: Path, config: TypographyConfig) -> Path:
    """실제 infer CLI와 같은 방식으로 plan artifact를 만들고 경로를 반환한다."""

    analysis = analyze_pdf(INPUT_PDF, config)
    inference = infer_bookmarks(analysis, config)
    artifacts = write_inference_artifacts(output_dir, inference)
    return artifacts["bookmark_plan"]


def main() -> None:
    if not INPUT_PDF.exists():
        raise FileNotFoundError(f"입력 PDF가 없다: {INPUT_PDF}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    default_plan_path = run_infer(OUTPUT_DIR / "default", TypographyConfig())
    no_fallback_plan_path = run_infer(
        OUTPUT_DIR / "no_position_fallback",
        TypographyConfig(position_fallback_enabled=False),
    )

    comparison = inspect_compare_plans(
        default_plan_path, no_fallback_plan_path, page_tolerance=0
    )

    summary: dict[str, Any] = {
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "plan_a_path": str(Path(comparison["plan_a_path"]).relative_to(ROOT_DIR)),
        "plan_b_path": str(Path(comparison["plan_b_path"]).relative_to(ROOT_DIR)),
        "plan_a_item_count": comparison["plan_a_item_count"],
        "plan_b_item_count": comparison["plan_b_item_count"],
        "added_count": comparison["added_count"],
        "removed_count": comparison["removed_count"],
        "matched_count": comparison["matched_count"],
        "unchanged_count": comparison["unchanged_count"],
        "moved_count": comparison["moved_count"],
        "level_changed_count": comparison["level_changed_count"],
        "source_changed_count": comparison["source_changed_count"],
        "removed_sample": [
            entry["before"]["title"]
            for entry in comparison["entries"]
            if entry["status"] == "removed"
        ][:5],
    }
    summary["finding"] = (
        f"position_fallback_enabled=False로 다시 추론하면 plan_a(기본)="
        f"{summary['plan_a_item_count']}개, plan_b(fallback 끔)="
        f"{summary['plan_b_item_count']}개. removed={summary['removed_count']}"
        f"(fallback이 찾았지만 fallback 끄면 사라지는 항목), "
        f"added={summary['added_count']}, unchanged={summary['unchanged_count']}."
    )

    OUTPUT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    record_showcase(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def record_showcase(summary: dict[str, Any]) -> None:
    """inspect compare 검증 결과를 showcase registry에 기록한다."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "compare_bookmark_plans()/inspect_compare_plans()를 실제 책 한 권의 "
            "서로 다른 두 TypographyConfig(기본값, position_fallback_enabled="
            "False) infer 결과로 검증한다."
        ),
        "inputs": [str(INPUT_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_PATH.relative_to(ROOT_DIR)),
        "finding": summary["finding"],
        "command": "uv run python showcase/023_bookmark_plan_compare.py",
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


if __name__ == "__main__":
    main()
