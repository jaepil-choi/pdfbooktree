"""experiment 018: 글씨 height tier를 LLM에 먹여 목차 계층을 복원한다.

experiment 017에서 TOC 줄의 textbox height만 k-미고정 밀도 클러스터링하면
사람이 보는 글씨 tier(큰 글씨=장 / 작은 글씨=항목)가 복원됨을 확인했다.
이 실험은 그 tier를 `[T1]/[T2]` 마커로 prompt에 입혀 LLM(solar-pro3)이 계층
레벨을 제대로 매기는지 검증한다.

비교를 위해 두 결과를 나란히 낸다.
- baseline: 현재 공개 인터페이스 `LlmTocExtractor`(tier 없는 평탄 텍스트).
- enriched: 같은 page를 height tier로 주석한 prompt + tier 우선 지시.

range 검출 노이즈를 빼려고 TOC page는 GT 라벨(answer_toc_ranges_manual.json)을
쓴다. 결과는 showcase 006처럼 들여쓰기 트리 '전체'를 txt로 남겨 눈으로 비교한다.

입력: 라벨의 not-indexed scanned OCR 2권(algorithms_to_live_by, algorithm_nine).
출력: experiments/outputs/018_toc_size_aware_llm_extraction/
    - <id>_baseline_tree.txt : 현재 평탄 추출 트리(전체)
    - <id>_enriched_tree.txt : tier 입힌 추출 트리(전체)
    - <id>_enriched_prompt.txt : LLM에 넘긴 enriched prompt(검증용)
    - summary.json
실행:
    uv run python experiments/018_toc_size_aware_llm_extraction.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import fitz
import numpy as np
from dotenv import load_dotenv
from scipy.signal import argrelextrema
from scipy.stats import gaussian_kde

from pdfbooktree import LlmTocExtractionConfig, LlmTocExtractor
from pdfbooktree.models import TocItem
from pdfbooktree.toc.llm_extract import build_toc_schema

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
LABELS_PATH = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "018_toc_size_aware_llm_extraction"

TARGET_IDS = ["algorithms_to_live_by", "algorithm_nine"]

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
MODEL = "solar-pro3"

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")

# enriched 경로 system prompt. 핵심: LLM은 레벨을 '추론'하지 않는다. 줄 앞 [Tn]의
# n을 level로 '복사'만 하고, 줄 분리/OCR 정리/페이지번호 추출만 한다. 계층은 글씨
# 크기 클러스터(tier)가 이미 정했다.
ENRICHED_SYSTEM_PROMPT = (
    "너는 책 목차(Table of Contents) 페이지에서 목차 항목을 구조화해 추출하는 도구다. "
    "입력의 각 줄 앞에는 그 줄 글씨 크기 tier가 [T1], [T2], ... 로 붙어 있다(T1이 가장 "
    "큰 글씨). 계층 레벨은 이미 이 tier로 정해졌으니 너는 레벨을 추론하지 마라.\n"
    "규칙:\n"
    "- level: 그 항목이 온 줄 앞 [Tn]의 n을 그대로 복사한다. 절대 스스로 판단하거나 "
    "바꾸지 마라. 한 줄을 여러 항목으로 쪼개도 모든 항목은 그 줄과 같은 n을 받는다.\n"
    "- [T1] 줄은 장/부 제목이다. OCR로 심하게 깨졌더라도 각 [T1] 줄은 반드시 항목 "
    "정확히 1개로 만든다(쪼개지도, 빼지도 마라). 제목 꼬리에 붙은 한자/기호 OCR 잡음"
    "(예: '살펴보는일을멈춈야할때-細龜'→'살펴보는 일을 멈춰야 할 때', '잊어라-臨'→'잊어라', "
    "'미래여區-園 O 뜨퍄'→'미래여')은 제거하고 제목만 남긴다.\n"
    "- 단 하나의 예외: [T1] 줄 텍스트가 글자 그대로 '목차'/'차례'/'Contents'/'Contents "
    "in brief'/'Brief Contents'처럼 그 페이지 머리말 한 마디뿐이면 그 줄에서는 항목을 "
    "만들지 마라.\n"
    "- 멀티 항목 분리는 [T2] 이하 줄에만 적용한다. 한 [T2] 줄에 여러 항목이 'I'/'|'/'·'/"
    "'•' 구분자와 페이지 번호로 합쳐져 있을 수 있다(OCR이 2단 목차를 한 줄로 읽음). "
    "예: '비서 문제 • 24 I 37%는 어디에서 • 28 I 연인의 뛰어들기 • 34' → 항목 3개로 "
    "분리하고 모두 그 줄의 tier를 받는다.\n"
    "- printed_page: 각 항목 제목 뒤(또는 '•'/'·' 뒤)에 인쇄된 페이지 번호. 없으면 null.\n"
    "- source_pdf_page: 그 항목이 나타난 목차 PDF page. 입력의 '--- PDF page N ---' "
    "마커 기준 N을 그대로 쓴다.\n"
    "- title은 OCR 노이즈를 정리해 깨끗한 제목으로 복원하되(예: '주처할때'→'주저할 때', "
    "'뛰어틀기'→'뛰어들기'), 의미는 바꾸지 말고 없는 항목/단어를 지어내지 않는다.\n"
    "- 항목은 목차에 나온 순서대로 반환한다."
)


def normalize_levels(items: list[TocItem]) -> list[TocItem]:
    """존재하는 최소 tier를 level 1로 당긴다(페이지 제목 tier가 빠진 경우 보정)."""

    if not items:
        return items
    base = min(item.level for item in items)
    if base == 1:
        return items
    return [
        TocItem(
            title=item.title,
            level=item.level - base + 1,
            printed_page=item.printed_page,
            raw_text=item.raw_text,
            source_pdf_page=item.source_pdf_page,
            confidence=item.confidence,
        )
        for item in items
    ]


def _case_id(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", text).strip("_")[:80]


def is_content_span(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


def extract_toc_lines(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """TOC page들에서 줄 단위 (대표 height, 텍스트)를 뽑는다(experiment 017과 동일)."""

    lines: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for pno in toc_pages:
            page = document.load_page(pno - 1)
            data = page.get_text("dict")
            for block in data["blocks"]:
                for line in block.get("lines", []):
                    content_heights: list[float] = []
                    parts: list[str] = []
                    for span in line["spans"]:
                        text = span["text"]
                        if not text.strip():
                            continue
                        parts.append(text.strip())
                        if is_content_span(text):
                            y0, y1 = span["bbox"][1], span["bbox"][3]
                            content_heights.append(round(y1 - y0, 2))
                    if not content_heights:
                        continue
                    lines.append(
                        {
                            "pdf_page": pno,
                            "height": max(content_heights),
                            "text": " ".join(parts),
                        }
                    )
    return lines


def cluster_cut_points(heights: list[float]) -> list[float]:
    """height 1D를 KDE 봉우리/골짜기로 클러스터링한 cut point를 돌려준다(k 미고정)."""

    arr = np.asarray(heights, dtype=float)
    if np.unique(arr).size == 1:
        return []
    kde = gaussian_kde(arr)
    grid = np.linspace(arr.min() - 1.0, arr.max() + 1.0, 1024)
    density = kde(grid)
    peak_idx = argrelextrema(density, np.greater)[0]
    valley_idx = argrelextrema(density, np.less)[0]
    if peak_idx.size == 0:
        return []
    peaks = [float(grid[i]) for i in peak_idx]
    cuts = [float(grid[vi]) for vi in valley_idx if peaks[0] < grid[vi] < peaks[-1]]
    return sorted(cuts)[: max(len(peaks) - 1, 0)]


def assign_tier(height: float, cut_points: list[float]) -> int:
    tier = 1
    for cut in sorted(cut_points, reverse=True):
        if height >= cut:
            return tier
        tier += 1
    return tier


def build_enriched_prompt(lines: list[dict[str, Any]], cut_points: list[float]) -> str:
    """각 줄에 [Tn] tier를 붙이고 PDF page 블록으로 묶은 prompt를 만든다."""

    blocks: list[str] = []
    current_page: int | None = None
    buf: list[str] = []
    for line in lines:
        if line["pdf_page"] != current_page:
            if buf:
                blocks.append("\n".join(buf))
            current_page = line["pdf_page"]
            buf = [f"--- PDF page {current_page} ---"]
        tier = assign_tier(line["height"], cut_points)
        buf.append(f"[T{tier}] {line['text']}")
    if buf:
        blocks.append("\n".join(buf))
    return "\n\n".join(blocks)


def call_enriched_llm(prompt_text: str, valid_pages: set[int]) -> list[TocItem]:
    """enriched prompt로 solar-pro3를 호출해 TocItem을 받는다."""

    from openai import OpenAI

    api_key = os.environ.get("UPSTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("UPSTAGE_API_KEY가 설정되지 않았다.")
    client = OpenAI(api_key=api_key, base_url=UPSTAGE_BASE_URL)
    schema = build_toc_schema(nullable_page=True, include_source_page=True)
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": ENRICHED_SYSTEM_PROMPT},
            {"role": "user", "content": prompt_text},
        ],
        response_format=schema,
        temperature=0.0,
    )
    content = response.choices[0].message.content or "{}"
    raw_items = json.loads(content).get("items", [])
    fallback = min(valid_pages)
    items: list[TocItem] = []
    for raw in raw_items:
        title = str(raw.get("title", "")).strip()
        if not title:
            continue
        page_value = raw.get("printed_page")
        src = raw.get("source_pdf_page")
        items.append(
            TocItem(
                title=title,
                level=int(raw.get("level") or 1),
                printed_page=int(page_value) if page_value else None,
                raw_text=title,
                source_pdf_page=int(src)
                if isinstance(src, int) and src in valid_pages
                else fallback,
                confidence=0.8,
            )
        )
    return items


def render_tree(items: list[TocItem]) -> list[str]:
    """level을 들여쓰기로 표현한 tree 전체를 만든다(자르지 않는다)."""

    out: list[str] = []
    for item in items:
        indent = "    " * max(item.level - 1, 0)
        page = item.printed_page if item.printed_page is not None else "-"
        out.append(f"{indent}[{page}] L{item.level} {item.title}")
    return out


def level_distribution(items: list[TocItem]) -> dict[str, int]:
    return {str(k): v for k, v in sorted(Counter(i.level for i in items).items())}


def run_book(label: dict[str, Any]) -> dict[str, Any]:
    pdf_path = ROOT_DIR / label["input_pdf"]
    case_id = label["id"]
    toc_pages: list[int] = label["toc_pages"]
    record: dict[str, Any] = {
        "id": case_id,
        "input_pdf": label["input_pdf"],
        "toc_pages": toc_pages,
    }
    if not pdf_path.exists():
        record["status"] = "missing_pdf"
        return record

    # --- baseline: 현재 공개 인터페이스(평탄 텍스트) ---
    baseline_items = LlmTocExtractor(LlmTocExtractionConfig()).extract(
        pdf_path, toc_pages
    )

    # --- enriched: height tier 주입 ---
    lines = extract_toc_lines(pdf_path, toc_pages)
    cut_points = cluster_cut_points([line["height"] for line in lines])
    prompt_text = build_enriched_prompt(lines, cut_points)
    (OUTPUT_DIR / f"{_case_id(case_id)}_enriched_prompt.txt").write_text(
        prompt_text + "\n", encoding="utf-8"
    )
    enriched_items = normalize_levels(call_enriched_llm(prompt_text, set(toc_pages)))

    # --- 트리 덤프(전체) ---
    base_tree = render_tree(baseline_items)
    enr_tree = render_tree(enriched_items)
    (OUTPUT_DIR / f"{_case_id(case_id)}_baseline_tree.txt").write_text(
        "\n".join(base_tree) + "\n", encoding="utf-8"
    )
    (OUTPUT_DIR / f"{_case_id(case_id)}_enriched_tree.txt").write_text(
        "\n".join(enr_tree) + "\n", encoding="utf-8"
    )

    record.update(
        {
            "status": "ok",
            "tier_cut_points": [round(c, 2) for c in cut_points],
            "baseline_item_count": len(baseline_items),
            "baseline_level_distribution": level_distribution(baseline_items),
            "enriched_item_count": len(enriched_items),
            "enriched_level_distribution": level_distribution(enriched_items),
            "baseline_tree_file": str(
                (OUTPUT_DIR / f"{_case_id(case_id)}_baseline_tree.txt").relative_to(
                    ROOT_DIR
                )
            ),
            "enriched_tree_file": str(
                (OUTPUT_DIR / f"{_case_id(case_id)}_enriched_tree.txt").relative_to(
                    ROOT_DIR
                )
            ),
            "enriched_tree_preview": enr_tree[:20],
        }
    )
    return record


def main() -> None:
    load_dotenv(ROOT_DIR / ".env")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    labels = {
        lab["id"]: lab
        for lab in json.loads(LABELS_PATH.read_text(encoding="utf-8"))["labels"]
    }
    results = [run_book(labels[i]) for i in TARGET_IDS if i in labels]

    summary = {
        "purpose": (
            "experiment 017의 height tier를 [Tn] 마커로 prompt에 입혀 solar-pro3가 "
            "목차 계층을 제대로 매기는지, 현재 평탄 baseline과 비교 검증한다."
        ),
        "source_experiment": "017_toc_font_size_cluster_hierarchy",
        "model": MODEL,
        "labels_source": str(LABELS_PATH.relative_to(ROOT_DIR)),
        "results": results,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=== height tier enriched LLM 목차 추출 vs 평탄 baseline ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"\n- {r['id']}: {r.get('status')}")
            continue
        print(f"\n- {r['id']} (tier cuts={r['tier_cut_points']})")
        print(
            f"    baseline: items={r['baseline_item_count']} "
            f"levels={r['baseline_level_distribution']}"
        )
        print(
            f"    enriched: items={r['enriched_item_count']} "
            f"levels={r['enriched_level_distribution']}"
        )
        print("    enriched tree preview:")
        for line in r["enriched_tree_preview"][:16]:
            print(f"      {line}")


if __name__ == "__main__":
    main()
