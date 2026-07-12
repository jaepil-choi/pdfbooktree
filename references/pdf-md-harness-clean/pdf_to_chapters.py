#!/usr/bin/env python3
"""Detect top-level chapters in a PDF and export each one as Markdown."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from pdf_to_markdown import PAGE_BREAK, looks_like_page_number, normalize_text, pages_to_markdown


KO_CHAPTER_RE = re.compile(
    r"^\s*(?:제\s*)?(?P<number>\d{1,3})\s*(?P<marker>장|잠)(?P<rest>.*)$"
)
EN_CHAPTER_RE = re.compile(
    r"^\s*(?P<marker>chapter|chap\.)\s+(?P<number>\d{1,3}|[ivxlcdm]+)(?P<rest>.*)$",
    re.IGNORECASE,
)
TOC_RE = re.compile(r"(?:목차|contents|table\s+of\s+contents)", re.IGNORECASE)
BODY_OPENER_RE = re.compile(
    r"(?:무엇을\s*배우|왜\s*필요|언제\s*필요|what\s+you|why\s+(?:is|do)|introduction)",
    re.IGNORECASE,
)


@dataclass
class Candidate:
    page: int
    number: int
    title: str
    score: int
    standalone: bool
    toc_like: bool
    raw_line: str
    reasons: list[str]
    source: str = "detected"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_pdf", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--pdftotext", default="pdftotext")
    parser.add_argument("--last-page", type=int)
    parser.add_argument("--dry-run", action="store_true", help="Print detected boundaries without writing Markdown.")
    parser.add_argument(
        "--min-confidence",
        type=int,
        default=5,
        help="Minimum candidate score required for a detected chapter.",
    )
    parser.add_argument(
        "--title-map",
        type=Path,
        help="Optional JSON object mapping chapter numbers to clean titles.",
    )
    parser.add_argument(
        "--boundary-map",
        type=Path,
        help="Optional JSON file with explicit section starts for non-standard books.",
    )
    return parser.parse_args()


def find_binary(name_or_path: str) -> str:
    binary = shutil.which(name_or_path)
    if binary:
        return binary
    path = Path(name_or_path)
    if path.exists() and path.is_file():
        return str(path)
    raise SystemExit(f"pdftotext was not found: {name_or_path}")


def extract_pages(pdf: Path, binary: str) -> list[str]:
    proc = subprocess.run(
        [binary, "-layout", "-enc", "UTF-8", str(pdf), "-"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "pdftotext failed")
    pages = normalize_text(proc.stdout).split(PAGE_BREAK)
    while pages and not pages[-1].strip():
        pages.pop()
    return pages


def roman_to_int(value: str) -> int:
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total = 0
    previous = 0
    for char in reversed(value.lower()):
        current = values[char]
        total += -current if current < previous else current
        previous = current
    return total


def clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip(" -:|_")
    title = re.sub(r"\s+(?:page\s*)?\d{1,4}\s*$", "", title, flags=re.IGNORECASE)
    return title.strip(" -:|_")


def nonempty_lines(page: str) -> list[str]:
    return [line.rstrip() for line in page.splitlines() if line.strip()]


def parse_chapter_line(line: str) -> tuple[int, str, bool] | None:
    match = KO_CHAPTER_RE.match(line) or EN_CHAPTER_RE.match(line)
    if match:
        number_text = match.group("number")
        number = int(number_text) if number_text.isdigit() else roman_to_int(number_text)
        return number, clean_title(match.group("rest")), not bool(match.group("rest").strip())
    return None


def title_from_following_lines(lines: list[str], index: int) -> str:
    parts: list[str] = []
    for line in lines[index + 1 : index + 4]:
        stripped = line.strip()
        if not stripped or looks_like_page_number(stripped):
            continue
        if parse_chapter_line(stripped) or stripped.startswith(("•", "-", "*")):
            break
        if len(stripped) > 100:
            break
        parts.append(stripped)
        if len(parts) == 2:
            break
    return clean_title(" ".join(parts))


def candidate_for_line(lines: list[str], index: int) -> tuple[int, str, bool, str] | None:
    parsed = parse_chapter_line(lines[index].strip())
    if not parsed:
        return None
    number, title, standalone = parsed
    if standalone:
        title = title_from_following_lines(lines, index)
    if not title:
        title = f"Chapter {number}"
    return number, title, standalone, lines[index].strip()


def detect_candidates(pages: list[str]) -> list[Candidate]:
    candidates: list[Candidate] = []
    page_candidates: list[list[tuple[int, str, bool, str]]] = []
    for page in pages:
        lines = nonempty_lines(page)
        found: list[tuple[int, str, bool, str]] = []
        for index in range(min(len(lines), 24)):
            candidate = candidate_for_line(lines, index)
            if candidate:
                found.append(candidate)
        page_candidates.append(found)

    for page_index, found in enumerate(page_candidates, start=1):
        if not found:
            continue
        distinct_numbers = {item[0] for item in found}
        lines = nonempty_lines(pages[page_index - 1])
        toc_like = bool(TOC_RE.search(" ".join(lines[:40]))) or len(distinct_numbers) >= 3
        body_opener = bool(BODY_OPENER_RE.search(" ".join(lines[:30])))
        for number, title, standalone, raw_line in found:
            line_position = next(
                (position for position, line in enumerate(lines) if line.strip() == raw_line),
                99,
            )
            score = 0
            reasons: list[str] = []
            if standalone:
                score += 5
                reasons.append("standalone marker")
            if line_position < 5:
                score += 3
                reasons.append("near top of page")
            elif line_position < 14:
                score += 1
                reasons.append("early on page")
            if len(title) >= 3:
                score += 1
                reasons.append("has title")
            if len(lines) >= 8:
                score += 1
                reasons.append("substantial page")
            if body_opener:
                score += 2
                reasons.append("chapter opener language")
            if toc_like:
                score -= 8
                reasons.append("TOC-like page")
            if re.search(r"\s\d{1,4}$", raw_line):
                score -= 1
                reasons.append("running-header page number")
            candidates.append(
                Candidate(
                    page=page_index,
                    number=number,
                    title=title,
                    score=score,
                    standalone=standalone,
                    toc_like=toc_like,
                    raw_line=raw_line,
                    reasons=reasons,
                )
            )
    return candidates


def choose_boundaries(candidates: list[Candidate], minimum_score: int) -> list[Candidate]:
    by_number: dict[int, list[Candidate]] = {}
    for candidate in candidates:
        if not candidate.toc_like:
            by_number.setdefault(candidate.number, []).append(candidate)

    selected_by_number: dict[int, Candidate] = {}
    for number, options in by_number.items():
        strong = [option for option in options if option.score >= minimum_score]
        if strong:
            strong.sort(key=lambda item: (-item.score, item.page))
            selected_by_number[number] = strong[0]

    # Some PDFs print chapter titles only as running headers. If a numbered
    # chapter is missing from the strong set, fill the gap from the page-order
    # interval between its neighboring detected chapters.
    numbers = sorted(by_number)
    for number in numbers:
        if number in selected_by_number:
            continue
        lower_pages = [item.page for item in selected_by_number.values() if item.number < number]
        upper_pages = [item.page for item in selected_by_number.values() if item.number > number]
        lower = max(lower_pages, default=0)
        upper = min(upper_pages, default=10**9)
        options = [item for item in by_number[number] if lower < item.page < upper]
        if options:
            options.sort(key=lambda item: (item.page, -item.score))
            selected_by_number[number] = options[0]

    selected = sorted(selected_by_number.values(), key=lambda item: item.page)
    deduped: list[Candidate] = []
    seen_pages: set[int] = set()
    for candidate in selected:
        if candidate.page in seen_pages:
            continue
        seen_pages.add(candidate.page)
        deduped.append(candidate)
    return deduped


def boundaries_from_map(path: Path) -> list[Candidate]:
    data = json.loads(path.read_text(encoding="utf-8"))
    sections = data.get("sections") if isinstance(data, dict) else data
    if not isinstance(sections, list) or not sections:
        raise SystemExit("--boundary-map must contain a non-empty 'sections' list")

    boundaries: list[Candidate] = []
    for item in sections:
        if not isinstance(item, dict) or "number" not in item or "start" not in item:
            raise SystemExit("Each boundary-map section needs 'number' and 'start'")
        boundaries.append(
            Candidate(
                page=int(item["start"]),
                number=int(item["number"]),
                title=str(item.get("title", f"Section {item['number']}")),
                score=100,
                standalone=True,
                toc_like=False,
                raw_line="boundary-map",
                reasons=["explicit boundary map"],
                source="boundary-map",
            )
        )
    boundaries.sort(key=lambda item: item.page)
    if len({item.page for item in boundaries}) != len(boundaries):
        raise SystemExit("Boundary-map sections must have unique start pages")
    return boundaries


def render_output(
    pages: list[str],
    output_dir: Path,
    boundaries: list[Candidate],
    last_page: int,
    title_map: dict[str, str] | None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    first_start = boundaries[0].page
    front = pages_to_markdown(
        PAGE_BREAK.join(pages[: first_start - 1]),
        "앞부분: 머리말·목차·용어 정리",
        keep_page_markers=False,
        start_page=1,
    )
    write_markdown(output_dir / "front-matter.md", front, 1, first_start - 1)

    for index, boundary in enumerate(boundaries):
        end = boundaries[index + 1].page - 1 if index + 1 < len(boundaries) else last_page
        title = (title_map or {}).get(str(boundary.number), boundary.title) or f"Chapter {boundary.number}"
        markdown = pages_to_markdown(
            PAGE_BREAK.join(pages[boundary.page - 1 : end]),
            f"{boundary.number}. {title}",
            keep_page_markers=False,
            start_page=boundary.page,
        )
        write_markdown(output_dir / f"ch-{boundary.number:02d}.md", markdown, boundary.page, end)

    report = {
        "boundaries": [
            {
                **asdict(boundary),
                "end_page": boundaries[index + 1].page - 1 if index + 1 < len(boundaries) else last_page,
            }
            for index, boundary in enumerate(boundaries)
        ],
        "page_count": last_page,
    }
    (output_dir / "detection-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report_lines = [
        "# Chapter Detection Report",
        "",
        f"- PDF pages scanned: {last_page}",
        f"- Chapters detected: {len(boundaries)}",
        "",
        "| Chapter | Pages | Score | Source | Title |",
        "| ---: | ---: | ---: | --- | --- |",
    ]
    for index, boundary in enumerate(boundaries):
        end = boundaries[index + 1].page - 1 if index + 1 < len(boundaries) else last_page
        title = (title_map or {}).get(str(boundary.number), boundary.title)
        report_lines.append(
            f"| {boundary.number} | {boundary.page}-{end} | {boundary.score} | {boundary.source} | {title} |"
        )
    (output_dir / "detection-report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    index_lines = [
        "# PDF Chapters",
        "",
        "챕터 경계는 목차와 본문 제목 후보를 로컬에서 분석해 자동 감지했습니다.",
        "경계 검토가 필요하면 `detection-report.md`를 확인하세요.",
        "",
    ]
    index_lines.extend(
        f"- `ch-{boundary.number:02d}.md`: {(title_map or {}).get(str(boundary.number), boundary.title)}"
        for boundary in boundaries
    )
    (output_dir / "README.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")


def write_markdown(path: Path, markdown: str, start_page: int, end_page: int) -> None:
    note = (
        "> PDF 텍스트 레이어에서 자동 추출한 Markdown입니다. "
        "원본 PDF의 OCR 품질에 따라 일부 오탈자나 수식 변환 오류가 남을 수 있습니다.\n"
        f"> 원본 PDF 페이지: {start_page}-{end_page}\n\n"
    )
    lines = markdown.split("\n", 2)
    if len(lines) == 3 and lines[0].startswith("# "):
        markdown = f"{lines[0]}\n\n{note}{lines[2]}"
    path.write_text(markdown, encoding="utf-8")


def main() -> int:
    args = parse_args()
    if not args.input_pdf.exists():
        raise SystemExit(f"Input PDF not found: {args.input_pdf}")

    pages = extract_pages(args.input_pdf, find_binary(args.pdftotext))
    last_page = args.last_page or len(pages)
    if last_page > len(pages):
        raise SystemExit(f"--last-page exceeds PDF page count ({len(pages)})")

    if args.boundary_map:
        boundaries = boundaries_from_map(args.boundary_map)
        if boundaries[0].page < 1 or boundaries[-1].page > last_page:
            raise SystemExit("Boundary-map page is outside the PDF")
    else:
        candidates = detect_candidates(pages[:last_page])
        boundaries = choose_boundaries(candidates, args.min_confidence)
    if not boundaries:
        raise SystemExit("No chapter boundaries found. Try a custom detector or inspect detection candidates.")

    print("Detected chapter boundaries:")
    for index, boundary in enumerate(boundaries):
        end = boundaries[index + 1].page - 1 if index + 1 < len(boundaries) else last_page
        print(f"  {boundary.number:02d}: PDF pages {boundary.page}-{end} | score={boundary.score} | {boundary.title}")

    if args.dry_run:
        return 0

    title_map: dict[str, str] | None = None
    if args.title_map:
        title_map = json.loads(args.title_map.read_text(encoding="utf-8"))
        if not isinstance(title_map, dict):
            raise SystemExit("--title-map must contain a JSON object")
    render_output(pages, args.output_dir, boundaries, last_page, title_map)
    print(f"Wrote {len(boundaries)} chapters to {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
