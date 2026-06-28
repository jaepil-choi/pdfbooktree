"""experiment 021: 단계적 prompt — 첫 페이지로 계층 스키마를 정하고 일관 적용한다.

experiment 020(단일 패스)에서 목차 전체를 한 번에 던지자 LLM이 장을 먼저 몰아내고
항목을 뒤에 몰아 순서가 깨졌다. 그래서 단계적 prompt로 바꾼다. 또 첫 시도에서
1단계 스키마가 글씨 크기를 무시하고 문장부호로 레벨을 과잉 발명해(algorithm_nine이
평탄한데 3레벨로) 회귀했다.

이번 설계의 핵심 두 제약:
1. content tier(계층 수)는 글씨 height 클러스터(experiment 017)가 정하고 고정한다.
   1단계 스키마는 그 tier 개수 N으로 레벨 수를 못 박고 이름/cue만 붙인다. tier->level
   매핑은 코드가 결정론적으로 소유한다(상위 tier=큰 글씨=level 1).
2. 2단계 추출 LLM은 tier/계층을 건드리지 않는다. 레벨을 출력하지 않고, 각 항목이 온
   줄의 [Tn] tier 숫자만 그대로 복사한다(structured output). 레벨은 코드가 매핑으로
   부여한다. LLM은 깨진 글씨 복원·항목 분리·페이지번호 추출만 한다.

페이지 단위로 추출해 순서를 보존한다. range 노이즈를 빼려고 TOC page는 GT 라벨을 쓴다.
결과는 showcase 006처럼 트리 전체를 txt로 남긴다.

출력: experiments/outputs/021_toc_staged_schema_then_extract/
    - <id>_schema.json    : 1단계 스키마(레벨 이름/cue) + 코드의 tier->level 매핑
    - <id>_tree.txt       : 최종 추출 트리(전체)
    - <id>_page{n}.json   : 페이지별 추출 항목
    - summary.json
실행:
    uv run python experiments/021_toc_staged_schema_then_extract.py
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
from pdfbooktree.utils.text_normalize import normalize_for_match

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
LABELS_PATH = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
OUTPUT_DIR = (
    ROOT_DIR / "experiments" / "outputs" / "021_toc_staged_schema_then_extract"
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

SCHEMA_SYSTEM_PROMPT = (
    "너는 책 목차의 '첫 페이지'를 보고 이 책 목차의 계층 스키마를 정의하는 도구다. "
    "각 줄 앞 [Tn]은 글씨 크기 tier다(T1이 가장 큰 글씨).\n"
    "중요: 계층 레벨 수는 이미 글씨 크기 클러스터로 정해졌다. 사용자가 알려주는 tier "
    "개수만큼만 레벨을 정의하고, 같은 글씨 크기를 번호·문장부호만으로 더 쪼개거나 합치지 "
    "마라. 큰 글씨 tier가 상위 레벨(1)이다.\n"
    "각 레벨에 level(1부터), name(예: 장/절/소절, chapter/section), cues(그 레벨을 알아보는 "
    "신호: 어떤 글씨 tier인지 등), examples(첫 페이지에서 그 레벨에 해당하는 제목 1~3개)를 "
    "적는다. '목차'/'Contents' 같은 페이지 머리말은 레벨에서 제외한다. 이 스키마는 이후 이 "
    "책의 모든 목차 페이지에 똑같이 적용된다."
)

EXTRACT_SYSTEM_PROMPT = (
    "너는 책 목차 페이지에서 항목을 추출하는 도구다. 아래 [계층 스키마]는 이 책 전체에 "
    "일관 적용되는 레벨 정의이고, 각 줄 앞 [Tn]은 그 줄의 글씨 크기 tier다.\n"
    "절대 규칙: 계층/레벨/tier는 네가 정하지 않는다. 각 항목의 tier는 그 항목이 나온 줄의 "
    "[Tn] 숫자(n)를 '그대로 복사'만 한다. tier를 바꾸거나 새로 만들거나 추론하지 마라. "
    "한 줄을 여러 항목으로 쪼개면 모든 조각은 그 줄과 같은 tier를 받는다.\n"
    "너가 하는 일은 다음뿐이다.\n"
    "- 깨진 OCR 글씨 복원: 깨진 제목을 깨끗하게 고친다(예: '살펴보는일을멈춈야할때-細龜'→"
    "'살펴보는 일을 멈춰야 할 때', '미래여區-園 O 뜨퍄'→'미래를 내다보라'). 보이는 글자만 "
    "살려 복원하고 없는 내용을 지어내지 않는다.\n"
    "- 항목 분리: 한 줄에 여러 항목이 'I'/'|'/'·'/'•' 구분자와 페이지 번호로 합쳐져 있으면 "
    "각 항목으로 분리한다. 예: '비서 문제 • 24 I 37%는 어디에서 • 28' → 항목 2개.\n"
    "- 페이지 번호: printed_page는 제목 뒤(또는 '•'/'·' 뒤)의 인쇄 페이지 번호. 없으면 null.\n"
    "- 글씨가 깨진 줄도 빼지 말고 반드시 항목으로 낸다.\n"
    "- '목차'/'Contents' 같은 머리말 한 마디 줄은 항목으로 만들지 않는다.\n"
    "- 항목은 이 페이지에 나온 순서 그대로 반환한다."
)

# 2단계 structured output: tier는 줄에서 복사, level은 코드가 매핑한다(LLM은 level을 내지 않음).
EXTRACT_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "toc_page_extraction",
        "schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tier": {
                                "type": "integer",
                                "description": "그 항목이 나온 줄의 [Tn] 숫자를 그대로 복사.",
                            },
                            "title": {"type": "string"},
                            "printed_page": {"type": ["integer", "null"]},
                        },
                        "required": ["tier", "title", "printed_page"],
                    },
                }
            },
            "required": ["items"],
        },
    },
}


def build_hierarchy_schema_format(n_levels: int) -> dict[str, Any]:
    """레벨 수를 정확히 n_levels개로 못 박는 1단계 응답 스키마."""

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "hierarchy_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "levels": {
                        "type": "array",
                        "minItems": n_levels,
                        "maxItems": n_levels,
                        "items": {
                            "type": "object",
                            "properties": {
                                "level": {"type": "integer"},
                                "name": {"type": "string"},
                                "cues": {"type": "string"},
                                "examples": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["level", "name", "cues", "examples"],
                        },
                    }
                },
                "required": ["levels"],
            },
        },
    }


def _case_id(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", text).strip("_")[:80]


def is_content_span(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


def is_title_word(text: str) -> bool:
    return normalize_for_match(text) in _TITLE_WORDS


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


def content_tier_to_level(
    lines: list[dict[str, Any]], cuts: list[float]
) -> dict[int, int]:
    """제목 머리말을 뺀 content tier를 정렬해 상위 tier=level 1로 매핑한다."""

    content_tiers = sorted(
        {
            assign_tier(ln["height"], cuts)
            for ln in lines
            if not is_title_word(ln["text"])
        }
    )
    return {tier: idx + 1 for idx, tier in enumerate(content_tiers)}


def annotate_page(lines: list[dict[str, Any]], pno: int, cuts: list[float]) -> str:
    out = [f"--- PDF page {pno} ---"]
    for line in lines:
        if line["pdf_page"] != pno:
            continue
        out.append(f"[T{assign_tier(line['height'], cuts)}] {line['text']}")
    return "\n".join(out)


def _client():
    from openai import OpenAI

    api_key = os.environ.get("UPSTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("UPSTAGE_API_KEY가 설정되지 않았다.")
    return OpenAI(api_key=api_key, base_url=UPSTAGE_BASE_URL)


def decide_schema(first_page_text: str, n_levels: int, tier_levels: dict[int, int]) -> dict[str, Any]:
    """1단계: 클러스터가 고정한 tier 개수로 계층 스키마(이름/cue)를 결정한다."""

    tier_map_desc = ", ".join(
        f"T{tier}=level {lvl}" for tier, lvl in sorted(tier_levels.items())
    )
    user = (
        f"글씨 크기 클러스터 결과, 이 책 목차의 content 글씨 tier는 {n_levels}개다 "
        f"({tier_map_desc}). 따라서 레벨도 정확히 {n_levels}개로 정의하라. 더 쪼개거나 "
        f"합치지 마라.\n\n[첫 목차 페이지]\n{first_page_text}"
    )
    response = _client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SCHEMA_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        response_format=build_hierarchy_schema_format(n_levels),
        temperature=0.0,
    )
    return json.loads(response.choices[0].message.content or "{}")


def extract_page(
    page_text: str,
    schema: dict[str, Any],
    pno: int,
    tier_levels: dict[int, int],
) -> list[TocItem]:
    """2단계: 스키마 동봉, structured output으로 한 페이지를 추출한다.

    LLM은 tier만 복사하고 level은 내지 않는다. level은 코드가 tier_levels로 매핑한다.
    """

    schema_str = json.dumps(schema, ensure_ascii=False, indent=2)
    user = (
        f"[계층 스키마 — 이 책 전체에 일관 적용]\n{schema_str}\n\n"
        f"[추출할 목차 페이지]\n{page_text}"
    )
    response = _client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        response_format=EXTRACT_RESPONSE_FORMAT,
        temperature=0.0,
    )
    raw_items = json.loads(response.choices[0].message.content or "{}").get("items", [])
    max_level = max(tier_levels.values()) if tier_levels else 1
    items: list[TocItem] = []
    for raw in raw_items:
        title = str(raw.get("title", "")).strip()
        if not title or is_title_word(title):
            continue
        tier = int(raw.get("tier") or 1)
        level = tier_levels.get(tier, max_level)  # 미지의 tier는 최하위로 clamp
        page_value = raw.get("printed_page")
        items.append(
            TocItem(
                title=title,
                level=level,
                printed_page=int(page_value) if page_value else None,
                raw_text=title,
                source_pdf_page=pno,
                confidence=0.8,
            )
        )
    return items


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
    tier_levels = content_tier_to_level(lines, cuts)  # 코드가 소유하는 tier->level
    n_levels = len(tier_levels)

    # 1단계: 첫 TOC 페이지 + 고정된 tier 수로 스키마(이름/cue) 결정.
    first_page_text = annotate_page(lines, toc_pages[0], cuts)
    schema = decide_schema(first_page_text, n_levels, tier_levels)
    (OUTPUT_DIR / f"{_case_id(case_id)}_schema.json").write_text(
        json.dumps(
            {
                "tier_to_level": {f"T{t}": lvl for t, lvl in sorted(tier_levels.items())},
                "llm_schema": schema,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # 2단계: 스키마 동봉, 페이지별 추출(순서 보존). level은 코드가 매핑.
    items: list[TocItem] = []
    for pno in toc_pages:
        page_text = annotate_page(lines, pno, cuts)
        page_items = extract_page(page_text, schema, pno, tier_levels)
        (OUTPUT_DIR / f"{_case_id(case_id)}_page{pno}.json").write_text(
            json.dumps(
                [
                    {"title": it.title, "level": it.level, "printed_page": it.printed_page}
                    for it in page_items
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        items.extend(page_items)

    tree = render_tree(items)
    (OUTPUT_DIR / f"{_case_id(case_id)}_tree.txt").write_text(
        "\n".join(tree) + "\n", encoding="utf-8"
    )

    record.update(
        {
            "status": "ok",
            "tier_cut_points": [round(c, 2) for c in cuts],
            "tier_to_level": {f"T{t}": lvl for t, lvl in sorted(tier_levels.items())},
            "schema_levels": [
                {"level": lv.get("level"), "name": lv.get("name"), "cues": lv.get("cues")}
                for lv in schema.get("levels", [])
            ],
            "item_count": len(items),
            "level_distribution": level_distribution(items),
            "tree_preview": tree[:24],
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
            "단계적 prompt. 1단계는 글씨 클러스터가 고정한 tier 수로 계층 스키마(이름/cue)를 "
            "정하고, 2단계는 그 스키마를 동봉해 페이지별로 structured output 추출한다. tier는 "
            "줄에서 복사만 하고 level은 코드가 tier->level 매핑으로 부여한다(LLM은 계층을 "
            "건드리지 않는다)."
        ),
        "source_experiment": "020_toc_extraction_repair_glyph_hierarchy",
        "model": MODEL,
        "labels_source": str(LABELS_PATH.relative_to(ROOT_DIR)),
        "results": results,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=== 단계적 스키마(글씨 tier 고정) + 페이지별 structured 추출 ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"\n- {r['id']}: {r.get('status')}")
            continue
        print(
            f"\n- {r['id']}: items={r['item_count']} levels={r['level_distribution']} "
            f"cuts={r['tier_cut_points']} tier_to_level={r['tier_to_level']}"
        )
        print("    schema levels:")
        for lv in r["schema_levels"]:
            print(f"      L{lv['level']} {lv['name']}: {lv['cues']}")
        print("    tree preview:")
        for line in r["tree_preview"][:18]:
            print(f"      {line}")


if __name__ == "__main__":
    main()
