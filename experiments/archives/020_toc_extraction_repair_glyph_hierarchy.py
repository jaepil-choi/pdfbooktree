"""experiment 020: 한 번의 추출에서 깨진 글씨와 계층을 LLM이 직접 고친다.

experiment 018에서 height tier를 prompt에 입히면 계층은 복원되지만, OCR이 심하게
깨진 [T1] 장 제목을 LLM이 일부 버리는 문제가 남았다(11개 장 중 7개만 유지).
재검증 루프(별도 critic 호출 반복)는 폐기하고, 대신 추출 한 번에서 LLM이
(a) 깨진 OCR 글씨를 복원하고 (b) 글씨 tier가 정한 계층대로 모든 장을 빠짐없이
출력하도록 강제하는 쪽으로 간다.

핵심: 클러스터(experiment 017)가 최상위 tier 줄=장을 결정론적으로 안다. 그래서
그 장 목록을 prompt에 명시적으로 박고 "이 N개를 하나도 빼지 말고 깨진 글씨를
고쳐 L1으로 내라"고 지시한다. 누락 판단을 LLM에 맡기지 않는다.

range 노이즈를 빼려고 TOC page는 GT 라벨을 쓴다. 결과는 showcase 006처럼 트리
전체를 txt로 남겨 눈으로 확인한다.

출력: experiments/outputs/020_toc_extraction_repair_glyph_hierarchy/
    - <id>_tree.txt   : 추출 트리(전체)
    - <id>_prompt.txt : LLM에 넘긴 user prompt(검증용)
    - summary.json
실행:
    uv run python experiments/020_toc_extraction_repair_glyph_hierarchy.py
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

from pdfbooktree.models import TocItem
from pdfbooktree.toc.llm_extract import build_toc_schema
from pdfbooktree.utils.text_normalize import normalize_for_match

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
LABELS_PATH = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
OUTPUT_DIR = (
    ROOT_DIR / "experiments" / "outputs" / "020_toc_extraction_repair_glyph_hierarchy"
)

TARGET_IDS = ["algorithms_to_live_by", "algorithm_nine"]
UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
MODEL = "solar-pro3"

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_TITLE_WORDS = {
    "목차",
    "차례",
    "contents",
    "contents in brief",
    "brief contents",
    "table of contents",
}

SYSTEM_PROMPT = (
    "너는 책 목차(Table of Contents)에서 항목을 구조화 추출하는 도구다. 입력의 각 줄 "
    "앞에는 글씨 크기 tier가 [T1], [T2], ... 로 붙어 있다(T1이 가장 큰 글씨). 계층은 이미 "
    "이 tier로 정해졌으니 레벨을 추론하지 말고 tier를 그대로 레벨로 쓴다.\n"
    "가장 중요한 두 가지를 반드시 지킨다.\n"
    "A) 순서 유지: 입력 줄을 위에서 아래 순서 그대로 처리해 항목을 만들고, 그 순서를 절대 "
    "바꾸지 마라. 한 장(chapter) 바로 다음에는 그 장에 속한 하위 항목들이 와야 한다. "
    "장들을 먼저 몰아서 내고 항목을 뒤에 몰면 안 된다.\n"
    "B) 장 누락 금지: '*'가 붙은 줄([T1*] 등)은 그 책의 장(chapter)이다. OCR이 심하게 "
    "깨졌더라도 그 자리에서 반드시 L1 항목 정확히 1개로 낸다(빼거나 다른 항목과 합치지 "
    "마라).\n"
    "그리고 깨진 글씨와 계층을 고쳐서 출력한다.\n"
    "1) 깨진 글씨 복원: OCR로 깨진 제목을 깨끗하게 고친다. 꼬리에 붙은 한자/기호 잡음"
    "(예: '살펴보는일을멈춈야할때-細龜'→'살펴보는 일을 멈춰야 할 때', '잊어라-臨'→'잊어라', "
    "'미래여區-園 O 뜨퍄'→'미래를 내다보라'처럼 의미가 살게)을 제거·교정하되, 확실치 "
    "않으면 보이는 글자만 살려 복원하고 없는 내용을 지어내지는 않는다.\n"
    "2) 계층: level은 그 줄 [Tn]의 n을 그대로 쓴다('*'는 무시하고 숫자만). 한 줄을 여러 "
    "항목으로 쪼개도 모두 같은 n을 받는다.\n"
    "규칙:\n"
    "- '*' 없는 [T2] 이하 줄에 여러 항목이 'I'/'|'/'·'/'•' 구분자와 페이지 번호로 합쳐져 "
    "있으면 각 항목으로 분리한다. 예: '비서 문제 • 24 I 37%는 어디에서 • 28' → 항목 2개.\n"
    "- 줄 텍스트가 글자 그대로 '목차'/'Contents'처럼 페이지 머리말 한 마디뿐이면 항목으로 "
    "만들지 않는다.\n"
    "- printed_page: 제목 뒤(또는 '•'/'·' 뒤)의 인쇄 페이지 번호. 없으면 null.\n"
    "- source_pdf_page: '--- PDF page N ---' 마커의 N.\n"
    "- 항목은 입력에 나온 순서 그대로 반환한다."
)


def _case_id(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", text).strip("_")[:80]


def is_content_span(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


def extract_toc_lines(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for pno in toc_pages:
            page = document.load_page(pno - 1)
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    heights: list[float] = []
                    parts: list[str] = []
                    for span in line["spans"]:
                        text = span["text"]
                        if not text.strip():
                            continue
                        parts.append(text.strip())
                        if is_content_span(text):
                            heights.append(round(span["bbox"][3] - span["bbox"][1], 2))
                    if heights:
                        lines.append(
                            {
                                "pdf_page": pno,
                                "height": max(heights),
                                "text": " ".join(parts),
                            }
                        )
    return lines


def cluster_cut_points(heights: list[float]) -> list[float]:
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


def is_title_word(text: str) -> bool:
    return normalize_for_match(text) in _TITLE_WORDS


def chapter_lines(lines: list[dict[str, Any]], cuts: list[float]) -> list[dict[str, Any]]:
    """제목 머리말을 뺀 최상위 content tier 줄(=L1 장이 되어야 하는 줄)."""

    content = [ln for ln in lines if not is_title_word(ln["text"])]
    if not content:
        return []
    min_tier = min(assign_tier(ln["height"], cuts) for ln in content)
    return [ln for ln in content if assign_tier(ln["height"], cuts) == min_tier]


def build_user_prompt(lines: list[dict[str, Any]], cuts: list[float]) -> str:
    """단일 in-order 스트림. 장(최상위 content tier) 줄은 [Tn*]로 표식한다."""

    chapters = chapter_lines(lines, cuts)
    chapter_ids = {id(ch) for ch in chapters}
    n_ch = len(chapters)

    blocks: list[str] = [
        f"아래는 한 책의 목차다. '*'가 붙은 [Tn*] 줄이 장(chapter)이며 총 {n_ch}개다. "
        "이 {n}개 장을 순서 그대로, 깨진 글씨를 고쳐 하나도 빠짐없이 L1으로 내라.".format(
            n=n_ch
        )
    ]
    current_page: int | None = None
    buf: list[str] = []
    for line in lines:
        if line["pdf_page"] != current_page:
            if buf:
                blocks.append("\n".join(buf))
            current_page = line["pdf_page"]
            buf = [f"--- PDF page {current_page} ---"]
        tier = assign_tier(line["height"], cuts)
        star = "*" if id(line) in chapter_ids else ""
        buf.append(f"[T{tier}{star}] {line['text']}")
    if buf:
        blocks.append("\n".join(buf))
    return "\n\n".join(blocks)


def call_extractor(user_prompt: str, valid_pages: set[int]) -> list[TocItem]:
    from openai import OpenAI

    api_key = os.environ.get("UPSTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("UPSTAGE_API_KEY가 설정되지 않았다.")
    client = OpenAI(api_key=api_key, base_url=UPSTAGE_BASE_URL)
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format=build_toc_schema(nullable_page=True, include_source_page=True),
        temperature=0.0,
    )
    raw_items = json.loads(response.choices[0].message.content or "{}").get("items", [])
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
    return normalize_levels(items)


def normalize_levels(items: list[TocItem]) -> list[TocItem]:
    if not items:
        return items
    base = min(it.level for it in items)
    if base == 1:
        return items
    return [
        TocItem(
            title=it.title,
            level=it.level - base + 1,
            printed_page=it.printed_page,
            raw_text=it.raw_text,
            source_pdf_page=it.source_pdf_page,
            confidence=it.confidence,
        )
        for it in items
    ]


def render_tree(items: list[TocItem]) -> list[str]:
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

    lines = extract_toc_lines(pdf_path, toc_pages)
    cuts = cluster_cut_points([ln["height"] for ln in lines])
    chapters = chapter_lines(lines, cuts)
    user_prompt = build_user_prompt(lines, cuts)
    (OUTPUT_DIR / f"{_case_id(case_id)}_prompt.txt").write_text(
        user_prompt + "\n", encoding="utf-8"
    )

    items = call_extractor(user_prompt, set(toc_pages))
    tree = render_tree(items)
    (OUTPUT_DIR / f"{_case_id(case_id)}_tree.txt").write_text(
        "\n".join(tree) + "\n", encoding="utf-8"
    )

    record.update(
        {
            "status": "ok",
            "tier_cut_points": [round(c, 2) for c in cuts],
            "expected_chapter_count": len(chapters),
            "item_count": len(items),
            "l1_count": sum(1 for it in items if it.level == 1),
            "level_distribution": level_distribution(items),
            "tree_preview": tree[:22],
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
            "재검증 루프 없이, 추출 한 번에서 LLM이 깨진 OCR 글씨를 복원하고 글씨 tier가 "
            "정한 계층대로 모든 장을 빠짐없이 출력하게 한다. 장 목록을 prompt에 명시적으로 "
            "박아 누락 판단을 LLM에 맡기지 않는다."
        ),
        "source_experiment": "018_toc_size_aware_llm_extraction",
        "model": MODEL,
        "labels_source": str(LABELS_PATH.relative_to(ROOT_DIR)),
        "results": results,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=== 추출 한 번에 깨진 글씨 + 계층 복원 (verify 루프 없음) ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"\n- {r['id']}: {r.get('status')}")
            continue
        print(
            f"\n- {r['id']}: L1={r['l1_count']}/{r['expected_chapter_count']}(장) "
            f"items={r['item_count']} levels={r['level_distribution']} "
            f"cuts={r['tier_cut_points']}"
        )
        print("    tree preview:")
        for line in r["tree_preview"][:16]:
            print(f"      {line}")


if __name__ == "__main__":
    main()
