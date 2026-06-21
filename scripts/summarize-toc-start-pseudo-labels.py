"""TOC start pseudo label 결과에서 confidence 상/하위 책을 출력한다."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TOC start pseudo label confidence 상/하위 row를 요약한다.",
    )
    parser.add_argument("input", type=Path, help="pseudo label JSON 또는 CSV 파일")
    parser.add_argument("--count", type=int, default=10, help="상/하위 출력 개수")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="요약 결과를 JSON으로 저장할 경로",
    )
    args = parser.parse_args()

    labels = load_labels(args.input)
    labeled = [
        label
        for label in labels
        if label.get("status") == "labeled"
        and label.get("toc_start_page") not in (None, "")
    ]
    ranked = sorted(
        labeled,
        key=lambda label: (
            float(label.get("confidence") or 0.0),
            str(label.get("root_relative_pdf") or label.get("input_pdf") or ""),
        ),
        reverse=True,
    )
    top = ranked[: args.count]
    bottom = list(reversed(ranked[-args.count :])) if ranked else []
    summary = {
        "input": str(args.input),
        "labeled_count": len(labeled),
        "top": [format_label(label) for label in top],
        "bottom": [format_label(label) for label in bottom],
    }

    print_summary(summary)
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def load_labels(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as file:
            return list(csv.DictReader(file))

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("labels"), list):
        return data["labels"]
    if isinstance(data, list):
        return data
    raise ValueError("labels 배열이 있는 JSON 또는 label row 배열 JSON이어야 한다.")


def format_label(label: dict[str, Any]) -> dict[str, Any]:
    return {
        "pdf": label.get("root_relative_pdf") or label.get("input_pdf"),
        "toc_start_page": to_int_or_none(label.get("toc_start_page")),
        "toc_end_page": to_int_or_none(label.get("toc_end_page")),
        "toc_page_count": to_int_or_none(label.get("toc_page_count")),
        "confidence": round(float(label.get("confidence") or 0.0), 6),
        "bookmark_count": to_int_or_none(label.get("bookmark_count")),
    }


def to_int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def print_summary(summary: dict[str, Any]) -> None:
    print(f"입력: {summary['input']}")
    print(f"labeled row 수: {summary['labeled_count']}")
    print()
    print("TOP confidence")
    print_rows(summary["top"])
    print()
    print("BOTTOM confidence")
    print_rows(summary["bottom"])


def print_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("(없음)")
        return
    for index, row in enumerate(rows, start=1):
        print(
            f"{index:02d}. confidence={row['confidence']:.6f} "
            f"start={row['toc_start_page']} end={row['toc_end_page']} "
            f"pages={row['toc_page_count']} bookmarks={row['bookmark_count']} "
            f"pdf={row['pdf']}"
        )


if __name__ == "__main__":
    main()
