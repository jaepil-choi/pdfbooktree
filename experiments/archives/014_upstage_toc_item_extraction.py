"""experiment 014: Upstage LLM으로 목차 페이지에서 목차 항목을 추출한다.

목적:
- 탐지된 TOC page range를 입력으로 받아, Upstage LLM이 목차 항목
  (title / level / printed_page)을 구조화 JSON으로 뽑게 한다.
- 같은 PDF에 두 입력 경로를 동시에 돌려 비교한다.
    - path A (text): OCR text layer 라인 텍스트 -> solar-pro2 chat
    - path B (image): TOC page 렌더 이미지 -> information-extract
- bookmark가 있는 영어 3권은 bookmark title을 weak label로 써서
  item precision/recall을 계산한다. bookmark가 없는 한국어 2권은
  추출 항목 수와 printed_page 단조성으로 정성 평가한다.

이 단계의 위치: LLM-primary item parser (기존 regex parse.py 대체 후보).
실험 규칙상 테스트/implementation note는 만들지 않는다.

실행:
    uv run python experiments/014_upstage_toc_item_extraction.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
from dotenv import load_dotenv
from openai import OpenAI
from rapidfuzz import fuzz

# src 패키지 재사용
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pdfbooktree.pdf.bookmarks import (  # noqa: E402
    extract_existing_bookmarks,
    title_has_letter,
)
from pdfbooktree.pdf.text import (  # noqa: E402
    extract_page_texts,
    extract_selected_page_texts,
)
from pdfbooktree.toc.detect import detect_toc_pages  # noqa: E402
from pdfbooktree.toc.features import calculate_page_features  # noqa: E402

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "014_upstage_toc_item_extraction"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
# Information Extraction은 chat completions와 다른 별도 엔드포인트를 쓴다.
UPSTAGE_IE_BASE_URL = "https://api.upstage.ai/v1/information-extraction"
TEXT_MODEL = "solar-pro2"
IMAGE_MODEL = "information-extract"

# image path 비용/payload 제어용 상한
MAX_IMAGE_PAGES = 12
IMAGE_DPI = 150
# bookmark title 매칭 임계값 (token_set_ratio)
MATCH_THRESHOLD = 80
# Korean 처럼 정답 range가 없을 때 TOC 탐색에 쓰는 앞부분 page 수
DETECT_MAX_PAGES = 40


# 입력 PDF: 영어 3권은 검수된 TOC range가 있고, 한국어 2권은 None이라
# 휴리스틱 detector로 TOC range를 추정한다.
INPUT_PDFS: list[dict[str, Any]] = [
    {
        "id": "john_hull",
        "path": ROOT_DIR
        / "data"
        / "native-pdf-indexed"
        / "John Hull - Options, Futures, and Other Derivatives, Global Edition-Pearson (2021).pdf",
        "toc_pages": list(range(5, 16)),
        "has_bookmarks": True,
    },
    {
        "id": "shreve_binomial",
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-indexed"
        / "(Springer Finance) Steven E. Shreve - Stochastic Calculus for Finance I The Binomial Asset Pricing Model-Springer (2005)-indexed.pdf",
        "toc_pages": list(range(3, 12)),
        "has_bookmarks": True,
    },
    {
        "id": "luenberger_investment_science",
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-indexed"
        / "David G. Luenberger, Investment Science 2nd - adobeOCR - indexed.pdf",
        "toc_pages": list(range(7, 21)),
        "has_bookmarks": True,
    },
    {
        "id": "algorithm_nine",
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-not-indexed"
        / "미래를_바꾼_아홉가지_알고리즘_-_존_맥코믹-compressed[algorithm cs book].pdf",
        "toc_pages": None,
        "has_bookmarks": False,
    },
    {
        "id": "algorithms_to_live_by",
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-not-indexed"
        / "알고리즘_인생을계산하다_The_computer_science_of_human_decisions_-_BrianChristian.pdf",
        "toc_pages": None,
        "has_bookmarks": False,
    },
]


# Upstage structured output용 JSON schema. printed_page 타입만 경로별로 다르다.
# solar-pro2(text)는 ["integer","null"] union을 받지만, information-extract(image)는
# 단일 타입만 허용하므로 IE 경로는 integer로 둔다(없으면 0).
def build_toc_schema(nullable_page: bool) -> dict[str, Any]:
    """목차 추출용 json_schema response_format을 만든다."""

    if nullable_page:
        page_type: Any = ["integer", "null"]
        page_desc = "목차에 인쇄된 페이지 번호. 없으면 null."
    else:
        page_type = "integer"
        page_desc = "목차에 인쇄된 페이지 번호. 없으면 0."
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "toc_extraction",
            "schema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "description": "목차 항목 제목. 번호가 있으면 번호 포함.",
                                },
                                "level": {
                                    "type": "integer",
                                    "description": "계층 레벨. 최상위 chapter/장/부=1, 하위 절=2, 그 하위=3.",
                                },
                                "printed_page": {
                                    "type": page_type,
                                    "description": page_desc,
                                },
                            },
                            "required": ["title", "level", "printed_page"],
                        },
                    }
                },
                "required": ["items"],
            },
        },
    }


TEXT_SCHEMA = build_toc_schema(nullable_page=True)
IE_SCHEMA = build_toc_schema(nullable_page=False)


SYSTEM_PROMPT = (
    "너는 책 목차(Table of Contents) 페이지에서 목차 항목을 구조화해 추출하는 도구다. "
    "주어진 텍스트/이미지는 한 책의 목차 페이지다. 각 목차 항목을 title, level, "
    "printed_page로 추출하라. 규칙:\n"
    "- title: 항목 제목. 번호(예: '1.1', '제2장', 'Chapter 3', 'Appendix A')가 있으면 포함한다.\n"
    "- level: 'Chapter N'/'제N장'/'N부'/'Part'/'Appendix'/최상위 번호(예: '1 ')는 1, "
    "'1.1'은 2, '1.1.1'은 3. 들여쓰기와 번호 깊이를 함께 본다.\n"
    "- printed_page: 항목 줄 끝(또는 우측)에 인쇄된 페이지 번호. 점선 leader가 깨졌어도 "
    "숫자를 찾는다. 페이지 번호가 없으면 null.\n"
    "- 목차 항목이 아닌 머리말/그림/표지 텍스트, running header, 페이지 번호만 있는 줄은 제외한다.\n"
    "- OCR로 깨진 제목은 합리적으로 복원하되 없는 항목을 지어내지 않는다.\n"
    "- 항목은 목차에 나온 순서대로 반환한다."
)


def get_clients() -> tuple[OpenAI, OpenAI]:
    """chat용과 Information Extraction용 Upstage client를 만든다."""

    load_dotenv(ROOT_DIR / ".env")
    api_key = os.environ.get("UPSTAGE_API_KEY")
    if not api_key:
        raise RuntimeError(".env에 UPSTAGE_API_KEY가 없다.")
    chat_client = OpenAI(api_key=api_key, base_url=UPSTAGE_BASE_URL)
    ie_client = OpenAI(api_key=api_key, base_url=UPSTAGE_IE_BASE_URL)
    return chat_client, ie_client


def resolve_toc_pages(pdf: dict[str, Any]) -> tuple[list[int], str]:
    """검수 range가 있으면 그대로, 없으면 휴리스틱 detector로 TOC range를 정한다."""

    if pdf["toc_pages"]:
        return pdf["toc_pages"], "reviewed_range"

    pages = extract_page_texts(pdf["path"], max_pages=DETECT_MAX_PAGES)
    with fitz.open(pdf["path"]) as document:
        total_pages = document.page_count
    features = calculate_page_features(pages, total_pages)
    result = detect_toc_pages(features)
    if result.pages:
        return result.pages, f"heuristic_detect(conf={result.confidence:.2f})"
    # 탐지 실패 시 앞부분 fallback
    return list(range(1, 11)), "fallback_first_10"


def build_text_prompt(pages: list[Any]) -> str:
    """TOC page 라인 텍스트를 page marker와 함께 이어붙인다."""

    blocks: list[str] = []
    for page in pages:
        body = "\n".join(page.lines) if page.lines else page.text
        blocks.append(f"--- PDF page {page.pdf_page} ---\n{body}")
    return "\n\n".join(blocks)


def render_pages_to_base64(pdf_path: Path, toc_pages: list[int]) -> list[str]:
    """TOC page들을 PNG base64로 렌더링한다."""

    images: list[str] = []
    with fitz.open(pdf_path) as document:
        for pdf_page in toc_pages[:MAX_IMAGE_PAGES]:
            page = document.load_page(pdf_page - 1)
            pix = page.get_pixmap(dpi=IMAGE_DPI)
            images.append(base64.b64encode(pix.tobytes("png")).decode("ascii"))
    return images


def call_text_path(client: OpenAI, prompt_text: str) -> dict[str, Any]:
    """path A: solar-pro2 chat으로 텍스트에서 추출한다."""

    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt_text},
        ],
        response_format=TEXT_SCHEMA,
        temperature=0.0,
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def call_image_path(ie_client: OpenAI, images_b64: list[str]) -> dict[str, Any]:
    """path B: information-extract로 페이지 이미지에서 추출한다.

    Information Extraction은 content에 이미지 1개만 허용하므로 page별로
    호출하고 결과 items를 순서대로 병합한다.
    """

    merged_items: list[dict[str, Any]] = []
    for image_b64 in images_b64:
        response = ie_client.chat.completions.create(
            model=IMAGE_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": (
                                    "data:application/octet-stream;"
                                    f"base64,{image_b64}"
                                )
                            },
                        }
                    ],
                }
            ],
            response_format=IE_SCHEMA,
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        merged_items.extend(parsed.get("items", []))
    return {"items": merged_items}


def monotonic_fraction(items: list[dict[str, Any]]) -> float | None:
    """printed_page가 직전 항목보다 작지 않은 비율을 잰다."""

    pages = [it["printed_page"] for it in items if it.get("printed_page")]
    if len(pages) < 2:
        return None
    non_decreasing = sum(1 for a, b in zip(pages, pages[1:]) if b >= a)
    return non_decreasing / (len(pages) - 1)


def evaluate_against_bookmarks(
    items: list[dict[str, Any]], bookmark_titles: list[str]
) -> dict[str, Any]:
    """title-only rapidfuzz 매칭으로 item precision/recall을 계산한다.

    bookmark target page와 목차 printed_page는 offset만큼 다르므로
    page는 보지 않고 title로만 매칭한다. OCR 제목이 전부 대문자거나
    '02' vs '2'처럼 표기가 갈리므로 소문자로 정규화한 뒤 비교한다.
    """

    item_titles = [it["title"] for it in items]
    norm_items = [t.lower() for t in item_titles]
    norm_bookmarks = [t.lower() for t in bookmark_titles]
    matched_items = 0
    for item_title in norm_items:
        best = max(
            (fuzz.token_set_ratio(item_title, bt) for bt in norm_bookmarks),
            default=0,
        )
        if best >= MATCH_THRESHOLD:
            matched_items += 1
    matched_bookmarks = 0
    for bt in norm_bookmarks:
        best = max(
            (fuzz.token_set_ratio(bt, it) for it in norm_items),
            default=0,
        )
        if best >= MATCH_THRESHOLD:
            matched_bookmarks += 1
    precision = matched_items / len(item_titles) if item_titles else 0.0
    recall = matched_bookmarks / len(bookmark_titles) if bookmark_titles else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return {
        "item_count": len(item_titles),
        "bookmark_count": len(bookmark_titles),
        "matched_items": matched_items,
        "matched_bookmarks": matched_bookmarks,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def run_path(label: str, fn) -> dict[str, Any]:
    """한 경로를 호출하고 에러를 잡아 결과 dict로 만든다."""

    try:
        parsed = fn()
        items = parsed.get("items", [])
        return {"ok": True, "items": items, "raw": parsed}
    except Exception as exc:  # noqa: BLE001 - 실험이라 광범위 캐치 후 기록
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}


def summarize_pdf(
    pdf: dict[str, Any], chat_client: OpenAI, ie_client: OpenAI
) -> dict[str, Any]:
    """단일 PDF에 두 경로를 돌리고 평가까지 한다."""

    toc_pages, toc_source = resolve_toc_pages(pdf)
    pages = extract_selected_page_texts(pdf["path"], toc_pages)
    prompt_text = build_text_prompt(pages)
    images_b64 = render_pages_to_base64(pdf["path"], toc_pages)

    text_result = run_path("text", lambda: call_text_path(chat_client, prompt_text))
    image_result = run_path("image", lambda: call_image_path(ie_client, images_b64))

    bookmark_titles: list[str] = []
    if pdf["has_bookmarks"]:
        bookmarks = extract_existing_bookmarks(pdf["path"])
        bookmark_titles = [
            b["title"]
            for b in bookmarks
            if b["title"] and title_has_letter(b["title"])
        ]

    def eval_path(result: dict[str, Any]) -> dict[str, Any]:
        if not result["ok"]:
            return {"error": result["error"]}
        if bookmark_titles:
            return evaluate_against_bookmarks(result["items"], bookmark_titles)
        return {
            "item_count": len(result["items"]),
            "printed_page_monotonic_fraction": monotonic_fraction(result["items"]),
        }

    summary = {
        "id": pdf["id"],
        "pdf": pdf["path"].name,
        "toc_pages": toc_pages,
        "toc_source": toc_source,
        "image_pages_used": min(len(toc_pages), MAX_IMAGE_PAGES),
        "has_bookmarks": pdf["has_bookmarks"],
        "text_path": {"ok": text_result["ok"], "eval": eval_path(text_result)},
        "image_path": {"ok": image_result["ok"], "eval": eval_path(image_result)},
    }

    # 경로별 원본/파싱 결과를 개별 파일로 저장
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for label, result in (("text", text_result), ("image", image_result)):
        out_path = OUTPUT_DIR / f"{pdf['id']}_{label}.json"
        out_path.write_text(
            json.dumps(
                {
                    "id": pdf["id"],
                    "toc_pages": toc_pages,
                    "ok": result["ok"],
                    "items": result["items"],
                    "error": result.get("error"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return summary


def build_finding(summaries: list[dict[str, Any]]) -> str:
    """experiments.json finding 문자열을 만든다."""

    parts: list[str] = []
    for s in summaries:
        t = s["text_path"]["eval"]
        i = s["image_path"]["eval"]
        if s["has_bookmarks"]:
            parts.append(
                f"{s['id']}(TOC {s['toc_pages'][0]}-{s['toc_pages'][-1]}): "
                f"text precision {t.get('precision')} recall {t.get('recall')} "
                f"f1 {t.get('f1')} (items {t.get('item_count')}), "
                f"image precision {i.get('precision')} recall {i.get('recall')} "
                f"f1 {i.get('f1')} (items {i.get('item_count')})."
            )
        else:
            parts.append(
                f"{s['id']}(TOC {s['toc_pages'][0]}-{s['toc_pages'][-1]}, "
                f"{s['toc_source']}): text items {t.get('item_count')} "
                f"mono {t.get('printed_page_monotonic_fraction')}, "
                f"image items {i.get('item_count')} "
                f"mono {i.get('printed_page_monotonic_fraction')}."
            )
    return " ".join(parts)


def append_to_experiments_json(finding: str) -> None:
    """experiments.json에 이번 실험 기록을 추가한다."""

    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "탐지된 TOC page range를 입력으로 Upstage LLM(solar-pro2 텍스트 경로와 "
            "information-extract 이미지 경로)을 호출해 목차 항목(title/level/printed_page)을 "
            "구조화 추출하고, bookmark가 있는 영어 3권은 bookmark title weak label로 "
            "item precision/recall을, bookmark 없는 한국어 2권은 항목 수와 "
            "printed_page 단조성으로 두 경로를 비교한다."
        ),
        "inputs": [str(pdf["path"].relative_to(ROOT_DIR)) for pdf in INPUT_PDFS],
        "outputs": f"experiments\\outputs\\{EXPERIMENT_ID}",
        "models": [TEXT_MODEL, IMAGE_MODEL],
        "temperature": 0.0,
        "finding": finding,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["experiments"] = [
        e for e in data["experiments"] if e.get("id") != EXPERIMENT_ID
    ]
    data["experiments"].append(entry)
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    chat_client, ie_client = get_clients()
    summaries: list[dict[str, Any]] = []
    for pdf in INPUT_PDFS:
        if not pdf["path"].exists():
            print(f"[skip] 파일 없음: {pdf['path']}")
            continue
        print(f"[run] {pdf['id']} ...")
        summary = summarize_pdf(pdf, chat_client, ie_client)
        summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    finding = build_finding(summaries)
    append_to_experiments_json(finding)
    print("\n=== finding ===")
    print(finding)


if __name__ == "__main__":
    main()
