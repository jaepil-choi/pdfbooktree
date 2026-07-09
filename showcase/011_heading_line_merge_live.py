"""showcase 011: 인접한 동일 tier line 병합이 실제 책에서 heading 후보를 올바르게 합치는지 보여준다.

실험 072/073(Zvi Bodie Investments, native-pdf-indexed)에서 발견한 문제: 이 책의
Chapter 1 표제는 실제로 "The Investment " / "Environment"처럼 같은 font size(36pt)의
두 line으로 나뉘어 렌더링된다. 병합 전(extract_typography_lines가 만드는 raw line)에는
이 둘이 서로 다른 line이라서, line 단위로 heading 후보를 만들면 fuzzy title 매칭이
fragment 하나에만 꽂혀 tree 하위 구조 전체가 어긋났다(072 parent_mismatch_sample 실측).

이 showcase는 synthetic PDF가 아니라 실제 Zvi Bodie Investments PDF에 대해
public API(Processor, skip_existing_bookmarks=False로 typography 추론을 강제)를
호출하고, artifact로 남는 실제 raw line과 실제 heading candidate를 비교해서
`_merge_adjacent_same_tier_lines`(src/pdfbooktree/typography/headings.py)가 이
책에서 실제로 두 line을 하나의 candidate로 합쳤는지 확인한다.

실행:
    uv run python showcase/011_heading_line_merge_live.py
출력:
    showcase/outputs/011_heading_line_merge_live/
        - (Processor가 만드는 실제 output PDF/markdown/artifact 전체)
        - result.json
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pdfbooktree.config import ProcessingConfig, TypographyConfig
from pdfbooktree.processor import Processor

ROOT_DIR = Path(__file__).resolve().parents[1]
SHOWCASE_ID = "011_heading_line_merge_live"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / SHOWCASE_ID
INPUT_PDF = (
    ROOT_DIR
    / "data"
    / "native-pdf-indexed"
    / "Zvi Bodie, Alex Kane, Alan Marcus - Investments-McGraw Hill (2021)[finance].pdf"
)
RESULT_JSON = OUTPUT_DIR / "result.json"
COMMAND = "uv run python showcase/011_heading_line_merge_live.py"
TARGET_PAGE = 30  # 실제 목차상 "Chapter 1: The Investment Environment"가 시작하는 page


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    result_holder = Processor(
        INPUT_PDF,
        OUTPUT_DIR,
        ProcessingConfig(
            skip_existing_bookmarks=False,  # 이미 bookmark가 있는 책이지만 typography 추론 경로를 강제로 태운다
            typography=TypographyConfig(),
        ),
    ).run()

    raw_lines = _load_jsonl(OUTPUT_DIR / "whole_book_lines.jsonl")
    candidates = _load_json(OUTPUT_DIR / "heading_candidates.json")

    page_raw_lines = [
        line
        for line in raw_lines
        if line["pdf_page"] == TARGET_PAGE and line["font_size"] >= 30
    ]
    page_candidates = [
        candidate for candidate in candidates if candidate["pdf_page"] == TARGET_PAGE
    ]

    raw_fragment_texts = [line["text"] for line in page_raw_lines]
    candidate_titles = [candidate["title"] for candidate in page_candidates]

    merged_title = next(
        (
            title
            for title in candidate_titles
            if "Investment" in title and "Environment" in title
        ),
        None,
    )
    fragment_survives_alone = any(
        title.strip() in {"The Investment", "Environment"} for title in candidate_titles
    )

    proof = {
        "raw_line_split_confirmed": len(page_raw_lines) >= 2
        and any("Investment" in text for text in raw_fragment_texts)
        and any("Environment" in text for text in raw_fragment_texts)
        and not any(
            "Investment" in text and "Environment" in text
            for text in raw_fragment_texts
        ),
        "merged_candidate_exists": merged_title is not None,
        "no_lone_fragment_candidate": not fragment_survives_alone,
        "processing_status": result_holder.status,
        "bookmark_count": result_holder.bookmark_count,
    }

    result = {
        "status": "processed",
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "output_dir": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "target_page": TARGET_PAGE,
        "raw_line_fragments_on_page": raw_fragment_texts,
        "heading_candidate_titles_on_page": candidate_titles,
        "merged_title": merged_title,
        "proof": proof,
        "ran_at": now(),
    }
    write_result(result)
    record_showcase(result)

    print("=== showcase 011: heading line merge (Zvi Bodie Investments, live) ===")
    print(f"page {TARGET_PAGE} raw line fragments (>=30pt): {raw_fragment_texts}")
    print(f"page {TARGET_PAGE} heading candidate titles: {candidate_titles}")
    print(f"proof: {proof}")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_json(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_result(result: dict[str, Any]) -> None:
    RESULT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def record_showcase(result: dict[str, Any]) -> None:
    data = (
        json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
        if SHOWCASE_JSON.exists()
        else {"showcases": []}
    )
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "src/pdfbooktree/typography/headings.py에 추가한 "
            "_merge_adjacent_same_tier_lines가 실제 Zvi Bodie Investments PDF에서 "
            "같은 page + 같은 font tier + 인접 line('The Investment ' / 'Environment', "
            "36pt)을 하나의 heading candidate로 합치는지 실제 Processor 실행으로 확인한다."
        ),
        "inputs": [str(INPUT_PDF.relative_to(ROOT_DIR))],
        "outputs": str(RESULT_JSON.relative_to(ROOT_DIR)),
        "finding": build_finding(result),
        "command": COMMAND,
        "ran_at": result.get("ran_at", now()),
    }
    data["showcases"] = [
        item for item in data.get("showcases", []) if item.get("id") != SHOWCASE_ID
    ]
    data["showcases"].append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def build_finding(result: dict[str, Any]) -> str:
    proof = result["proof"]
    return (
        f"page {result['target_page']}의 원본 raw line은 {result['raw_line_fragments_on_page']}로 "
        f"쪼개져 있었다(raw_line_split_confirmed={proof['raw_line_split_confirmed']}). "
        f"heading_candidates.json에는 merged_title={result['merged_title']!r}로 병합됐고, "
        f"merged_candidate_exists={proof['merged_candidate_exists']}, "
        f"no_lone_fragment_candidate={proof['no_lone_fragment_candidate']}. "
        f"processing_status={proof['processing_status']}, bookmark_count={proof['bookmark_count']}."
    )


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


if __name__ == "__main__":
    main()
