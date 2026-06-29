"""experiment 038: TOC page 탐지부터 bookmark 생성까지 full flow를 한 번에 잇는다.

흐름(모든 LLM 판정은 per-page 단위, 여러 page를 한 번에 넣지 않는다):

1. ML 기반 toc_page_range
   - 학습된 TOC page classifier(detect_toc_pages)로 후보 range를 얻는다.
2. LLM-corrected toc_page_range
   - LlmTocRangeReviewer가 page별 is_toc_page를 LLM으로 판정하며 anchor에서 한 page씩
     확장해 range를 확정한다(per-page).
3. per-page 1-pane balance 신호(soft)
   - 각 page의 좌우 content balance, shared_row, gutter_straddle를 결정론으로 구한다.
4. per-page 1 pane vs 2 pane 판정(vote)
   - 각 page를 reading A(한 단)·reading B(두 단) markdown으로 보여주고 balance 힌트와 함께
     문장 연결성으로 LLM이 고른다(per-page). page 투표로 책의 pane mode를 정한다.
5. deterministic toc level/hierarchy
   - pane mode에 맞춰 line을 재구성하고 height tier(KDE)·indent tier(KDE)로 결정론
     level을 부여한다(2 pane은 pane-local indent).
6. LLM structured 목차 추출
   - 1 pane은 그대로, 2 pane은 per-page 왼쪽 단 다음 오른쪽 단 순서로 텍스트를 만들고
     줄마다 [Ln] level 마커를 붙여 LLM이 항목을 structured output으로 뽑게 한다.
7. deterministic offset 적용 -> 최종 bookmark
   - estimate_page_offset로 printed->PDF offset을 구해 각 항목의 pdf_page를 정하고
     bookmark plan을 만들어 책별 JSON/CSV로 dump한다.

실행:
    uv run python experiments/038_full_flow_toc_to_bookmark.py

주의: stage 1은 학습된 모델 artifact가 필요하다
(outputs/300study_toc_page_dataset_model/toc_page_dataset_model.joblib).
없으면 해당 책은 stage 1에서 blocked로 기록하고 건너뛴다.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import numpy as np
from dotenv import load_dotenv

from pdfbooktree.alignment.offset import OffsetEstimationError, estimate_page_offset
from pdfbooktree.config import OffsetEstimationConfig, TocMlDetectionConfig
from pdfbooktree.pdf.text import extract_page_texts
from pdfbooktree.toc.detect import detect_toc_pages
from pdfbooktree.toc.features import calculate_page_features
from pdfbooktree.utils.text_normalize import normalize_for_match, normalize_text

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "038_full_flow_toc_to_bookmark"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
LABELS_JSON = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
MODEL_PATH = ROOT_DIR / "outputs" / "300study_toc_page_dataset_model" / "toc_page_dataset_model.joblib"
UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
MODEL = "solar-pro3"
MAX_SEARCH_PAGES = 80

TARGET_IDS = [
    "zvi_bodie_investments",
    "quant_world",
    "kim_econometrics_note1",
    "kim_econometrics_note2",
    "hankyung_reader",
]

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_DIGIT = re.compile(r"\d")
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_TITLE_WORDS = {
    "목차", "목 차", "차례", "contents", "contents in brief",
    "brief contents", "table of contents",
}


# ===========================================================================
# 공통: 텍스트/KDE 도구 (037 계열 재사용)
# ===========================================================================
def is_content_text(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped and (_HANGUL.search(stripped) or _LATIN2.search(stripped)))


def is_title_word(text: str) -> bool:
    return normalize_for_match(text) in _TITLE_WORDS


def cluster_cut_points(values: list[float], *, bandwidth: float | None = None, grid_size: int = 2048) -> list[float]:
    """1D 값 분포의 KDE valley를 cut point로 반환한다."""

    if not values:
        return []
    arr = np.asarray(values, dtype=float)
    if np.unique(arr).size <= 1:
        return []
    std = float(np.std(arr, ddof=1))
    if std <= 0.0:
        return []
    bandwidth = bandwidth or 1.06 * std * (len(arr) ** -0.2)
    if bandwidth <= 0.0 or not math.isfinite(bandwidth):
        return []
    grid = np.linspace(float(arr.min()) - 1.0, float(arr.max()) + 1.0, grid_size)
    z = (grid[:, None] - arr[None, :]) / bandwidth
    density = np.exp(-0.5 * z * z).sum(axis=1)
    peak_idx = [i for i in range(1, len(density) - 1) if density[i - 1] < density[i] > density[i + 1]]
    if not peak_idx:
        return []
    valley_idx = [i for i in range(1, len(density) - 1) if density[i - 1] > density[i] < density[i + 1]]
    peaks = [float(grid[i]) for i in peak_idx]
    return sorted(float(grid[i]) for i in valley_idx if min(peaks) < float(grid[i]) < max(peaks))


def band_low_first(value: float, cuts: list[float]) -> int:
    band = 1
    for cut in sorted(cuts):
        if value < cut:
            return band
        band += 1
    return band


def height_tier(height: float, cuts: list[float]) -> int:
    """큰 글씨가 T1이 되도록 height tier를 부여한다."""

    tier = 1
    for cut in sorted(cuts, reverse=True):
        if height >= cut:
            return tier
        tier += 1
    return tier


# ===========================================================================
# page box 추출과 line 재구성 (037 계열)
# ===========================================================================
def extract_page_boxes(pdf_path: Path, pdf_page: int) -> list[dict[str, Any]]:
    boxes: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        if pdf_page < 1 or pdf_page > document.page_count:
            return boxes
        page = document.load_page(pdf_page - 1)
        page_width = float(page.rect.width)
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span_index, span in enumerate(line.get("spans", [])):
                    text = normalize_text(span["text"])
                    if not text.strip():
                        continue
                    x0, y0, x1, y1 = [float(v) for v in span["bbox"]]
                    boxes.append(
                        {
                            "pdf_page": pdf_page,
                            "page_width": round(page_width, 2),
                            "span_index": span_index,
                            "text": text,
                            "x0": round(x0, 2),
                            "y0": round(y0, 2),
                            "x1": round(x1, 2),
                            "y1": round(y1, 2),
                            "span_height": round(y1 - y0, 2),
                            "is_content": is_content_text(text),
                        }
                    )
    return boxes


def _y_tier_by_box(boxes: list[dict[str, Any]]) -> dict[int, int]:
    content = [b for b in boxes if b["is_content"]]
    median_h = float(np.median([b["span_height"] for b in content])) if content else 4.0
    bandwidth = max(1.0, median_h * 0.3)
    cuts = cluster_cut_points([b["y0"] for b in content], bandwidth=bandwidth, grid_size=8192)
    return {id(b): band_low_first(b["y0"], cuts) for b in boxes}


def build_lines(boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """box를 y-row로 묶어 읽는 순서 line으로 만든다(단일 page)."""

    tier_by = _y_tier_by_box(boxes)
    grouped: dict[int, list[dict[str, Any]]] = {}
    for b in boxes:
        if not b["is_content"] and not _DIGIT.search(b["text"]):
            continue
        grouped.setdefault(tier_by[id(b)], []).append(b)
    lines: list[dict[str, Any]] = []
    for y_tier, members in sorted(grouped.items()):
        ordered = sorted(members, key=lambda v: (v["x0"], v["span_index"]))
        content = [m for m in ordered if m["is_content"]]
        if not content:
            continue
        lines.append(
            {
                "pdf_page": int(ordered[0]["pdf_page"]),
                "y_tier": y_tier,
                "text": normalize_text(" ".join(m["text"] for m in ordered)),
                "content_text": normalize_text(" ".join(m["text"] for m in content)),
                "content_min_x": round(min(m["x0"] for m in content), 2),
                "height": round(max(m["span_height"] for m in content), 2),
            }
        )
    return lines


def detect_gutter(content_boxes: list[dict[str, Any]], page_width: float) -> dict[str, Any]:
    """중앙 band에서 content box가 가장 적게 가로지르는 x를 gutter로 검출한다."""

    if not content_boxes or page_width <= 0:
        return {"gutter_x": round(page_width / 2, 2), "min_straddle": 0, "straddle_ratio": 0.0}
    low, high = 0.30 * page_width, 0.70 * page_width
    grid = np.linspace(low, high, 241)
    straddle = np.array([sum(1 for b in content_boxes if b["x0"] < cx < b["x1"]) for cx in grid])
    min_straddle = int(straddle.min())
    gutter_x = float(np.median(grid[straddle == straddle.min()]))
    n_rows = len(set(_y_tier_by_box(content_boxes).values())) or 1
    return {
        "gutter_x": round(gutter_x, 2),
        "min_straddle": min_straddle,
        "straddle_ratio": round(min_straddle / n_rows, 3),
    }


def page_balance(boxes: list[dict[str, Any]]) -> dict[str, Any]:
    """검출 gutter 기준 좌우 balance, shared-row 비율, gutter 깨끗함."""

    content = [b for b in boxes if b["is_content"]]
    page_width = float(boxes[0]["page_width"]) if boxes else 0.0
    gutter = detect_gutter(content, page_width)
    gx = gutter["gutter_x"]

    def side(b: dict[str, Any]) -> str:
        return "L" if (b["x0"] + b["x1"]) / 2 < gx else "R"

    left = sum(1 for b in content if side(b) == "L")
    right = len(content) - left
    balance = round(min(left, right) / max(left, right), 3) if left and right else 0.0
    tier_by = _y_tier_by_box(boxes)
    rows: dict[int, set[str]] = {}
    for b in content:
        rows.setdefault(tier_by[id(b)], set()).add(side(b))
    shared = sum(1 for s in rows.values() if s == {"L", "R"})
    shared_pct = round(shared / len(rows), 3) if rows else 0.0
    return {
        "left_content": left, "right_content": right, "balance": balance,
        "shared_row_pct": shared_pct, "gutter_x": gx,
        "gutter_straddle_ratio": gutter["straddle_ratio"],
    }


def split_page_panes(boxes: list[dict[str, Any]], gutter_x: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    left = [b for b in boxes if (b["x0"] + b["x1"]) / 2 < gutter_x]
    right = [b for b in boxes if (b["x0"] + b["x1"]) / 2 >= gutter_x]
    return build_lines(left), build_lines(right)


# ===========================================================================
# LLM 공통
# ===========================================================================
_CLIENT: Any = None


def client() -> Any:
    global _CLIENT
    if _CLIENT is None:
        from openai import OpenAI

        api_key = os.environ.get("UPSTAGE_API_KEY")
        if not api_key:
            raise RuntimeError("UPSTAGE_API_KEY가 설정되지 않았다.")
        _CLIENT = OpenAI(api_key=api_key, base_url=UPSTAGE_BASE_URL)
    return _CLIENT


def loads_lenient(content: str | None) -> dict[str, Any]:
    if not content:
        return {}
    text = content.strip()
    for cand in (text, (_FENCE.search(text).group(1) if _FENCE.search(text) else None)):
        if not cand:
            continue
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}


# ===========================================================================
# Stage 2: per-page is_toc_page 판정 -> 연속 확장으로 range 확정
# ===========================================================================
IS_TOC_SYSTEM = (
    "너는 PDF 책의 한 페이지가 목차(Table of Contents) 페이지인지 판정하는 분류기다.\n"
    "목차 페이지의 '필수 요건': 장/절 제목과 함께 본문 페이지 번호가 대부분의 줄에 동반된다"
    "(제목 옆/끝의 숫자, 점선 leader 뒤 숫자 등). 페이지 번호 없이 제목·주소·메모만 나열한 "
    "목록은 목차가 아니다.\n"
    "- 상세 목차(Contents)와 간략 목차(Brief Contents / Contents in brief)는 모두 목차다.\n"
    "- 표지, 헌사, 판권지, 서문/머리말, 추천사, 광고, 본문 첫 페이지는 목차가 아니다.\n"
    "너는 이 '한 페이지'가 목차인지(is_toc_page)와 페이지 번호가 동반되는지(has_page_numbers)만 "
    "판정한다. 목차 범위를 어디서 멈출지(halt)는 판단하지 않는다 — 그건 다음 페이지를 다시 "
    "너에게 물어 결정한다.\n"
    "반드시 주어진 JSON schema로만 답한다."
)
IS_TOC_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "is_toc_page",
        "schema": {
            "type": "object",
            "properties": {
                "is_toc_page": {"type": "boolean"},
                "has_page_numbers": {"type": "boolean"},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["is_toc_page", "has_page_numbers", "confidence", "reason"],
        },
    },
}


def judge_is_toc_page(pdf_page: int, snippet: str) -> dict[str, Any]:
    """한 page 텍스트만 보고 목차 page인지 LLM으로 판정한다(halt 판단 없음)."""

    user = (
        f"PDF page {pdf_page}의 텍스트다. 이 한 페이지가 목차 페이지인지 판정하라.\n\n"
        f"{snippet}"
    )
    response = client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": IS_TOC_SYSTEM}, {"role": "user", "content": user}],
        response_format=IS_TOC_RESPONSE_FORMAT,
        temperature=0.0,
    )
    return loads_lenient(response.choices[0].message.content)


def correct_toc_range(
    page_text: dict[int, str], seed_start: int, total_pages: int, *, max_anchor_scan: int = 20
) -> tuple[list[int], int | None, list[dict[str, Any]]]:
    """seed에서 anchor를 찾고, is_toc_page=true인 한 양방향으로 page를 계속 확장한다.

    LLM은 page별 is_toc_page만 판정하고, 멈춤은 '다음 page가 false'일 때 일어난다.
    즉 어떤 page가 목차면 반드시 다음 page도 LLM에 물어 이어간다.
    """

    cache: dict[int, dict[str, Any]] = {}
    trace: list[dict[str, Any]] = []

    def judge(pdf_page: int) -> bool:
        # 목차의 필수 요건: 페이지 번호 동반. is_toc_page=true여도 has_page_numbers=false면
        # 목차로 인정하지 않는다(예: zvi Brief Contents가 본문 페이지 번호 없이 잡히는 경우).
        if pdf_page in cache:
            cached = cache[pdf_page]
            return bool(cached.get("is_toc_page")) and bool(cached.get("has_page_numbers"))
        snippet = (page_text.get(pdf_page) or "")[:2500]
        result = (
            {"is_toc_page": False, "has_page_numbers": False, "reason": "빈 페이지"}
            if not snippet.strip()
            else judge_is_toc_page(pdf_page, snippet)
        )
        cache[pdf_page] = result
        is_toc = bool(result.get("is_toc_page"))
        has_pages = bool(result.get("has_page_numbers"))
        trace.append(
            {
                "pdf_page": pdf_page,
                "is_toc_page": is_toc,
                "has_page_numbers": has_pages,
                "accepted": is_toc and has_pages,
                "confidence": result.get("confidence"),
            }
        )
        return is_toc and has_pages

    # anchor: seed부터 앞으로 스캔해 첫 is_toc_page=true page를 찾는다.
    anchor: int | None = None
    page = max(1, seed_start)
    steps = 0
    while page <= total_pages and steps < max_anchor_scan:
        if judge(page):
            anchor = page
            break
        page += 1
        steps += 1
    if anchor is None:
        return [], None, trace

    # 앞으로 확장: is_toc_page=true인 한 다음 page로 계속 넘어간다(필수).
    end = anchor
    page = anchor + 1
    while page <= total_pages and page in page_text:
        if judge(page):
            end = page
            page += 1
        else:
            break
    # 뒤로 확장: anchor 앞쪽도 목차면 포함한다.
    start = anchor
    page = anchor - 1
    while page >= 1 and page in page_text:
        if judge(page):
            start = page
            page -= 1
        else:
            break
    return list(range(start, end + 1)), anchor, trace


# ===========================================================================
# Stage 4: per-page 1 pane vs 2 pane 판정 (037)
# ===========================================================================
PANE_SYSTEM = (
    "너는 책 목차 page 하나가 한 단(1 pane)인지 두 단(2 pane)인지 판정하는 도구다.\n"
    "같은 page에서 추출한 같은 텍스트를 두 읽기로 보여준다.\n"
    "- reading A: page를 한 단으로 보고 줄 순서대로 읽은 것.\n"
    "- reading B: page를 좌우 두 단으로 나눠 왼쪽 단을 위에서 아래로 읽은 뒤 오른쪽 단을 읽은 것.\n\n"
    "핵심 판단 기준은 '문장 연결성'이다. 어느 읽기에서 각 목차 항목의 제목 문장이 끊기지 않고 "
    "자연스럽게 이어지는가?\n"
    "- 한 단(1 pane) page를 억지로 두 단으로 나누면, 중앙을 넘어가는 긴 줄이 좌우로 잘려 "
    "제목 문장이 조각난다. 예: 왼쪽 단에 '...between lim and', 오른쪽 단에 'plim' 처럼 한 제목이 "
    "둘로 쪼개진다. 이러면 reading B가 깨진 것이므로 pane_count=1이다.\n"
    "- 진짜 두 단(2 pane) page를 한 단으로 읽으면, 좌우 칼럼의 서로 무관한 항목이 한 줄에 "
    "뒤섞이고 페이지 번호가 줄 중간에 낀다. 이러면 reading A가 깨진 것이므로 pane_count=2이다.\n\n"
    "보조 신호로 결정론 값 세 개를 준다. (1) 좌우 balance(0~1): 1에 가까우면 양쪽 단이 모두 꽉 찬 "
    "2단 신호, 0에 가까우면 한쪽만 차서 1단 신호. (2) shared_row_pct(0~1): 한 줄에 좌우가 함께 있는 "
    "비율. (3) gutter_straddle_ratio(0~ ): 검출한 세로 빈 띠(gutter)를 가로지르는 줄의 비율로, "
    "0에 가까우면 중앙에 깨끗한 빈 띠가 있어 2단, 높으면 긴 줄이 중앙을 가로질러 1단(또는 wrap) 신호다. "
    "이 신호들은 참고만 하고 최종 판단은 문장 연결성으로 한다.\n\n"
    "reading A에서 문장이 자연스러우면 pane_count=1, reading B에서 문장이 자연스러우면 pane_count=2."
)
PANE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "pane_choice",
        "schema": {
            "type": "object",
            "properties": {
                "pane_count": {"type": "integer"},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["pane_count", "confidence", "reason"],
        },
    },
}


def classify_page_pane(pdf_page: int, balance: dict[str, Any], whole_lines, left_lines, right_lines) -> dict[str, Any]:
    md_a = "## reading A (한 단)\n" + "\n".join(f"- {ln['text']}" for ln in whole_lines)
    md_b = (
        "## reading B (두 단: 왼쪽 먼저, 오른쪽 나중)\n### 왼쪽 단\n"
        + "\n".join(f"- {ln['text']}" for ln in left_lines)
        + "\n### 오른쪽 단\n"
        + "\n".join(f"- {ln['text']}" for ln in right_lines)
    )
    user = (
        f"목차 page {pdf_page}이다. 어느 읽기에서 항목 문장이 끊기지 않고 이어지는지 보고 pane_count를 답하라.\n\n"
        f"[결정론 보조 신호] balance={balance['balance']} "
        f"(L={balance['left_content']},R={balance['right_content']}), "
        f"shared_row_pct={balance['shared_row_pct']}, "
        f"gutter_straddle_ratio={balance['gutter_straddle_ratio']}\n\n{md_a}\n\n{md_b}\n"
    )
    response = client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": PANE_SYSTEM}, {"role": "user", "content": user}],
        response_format=PANE_RESPONSE_FORMAT,
        temperature=0.0,
    )
    parsed = loads_lenient(response.choices[0].message.content)
    return parsed


# ===========================================================================
# Stage 5: deterministic height/indent tier -> level
# ===========================================================================
def build_hierarchy_lines(pdf_path: Path, toc_pages: list[int], pane_mode: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """pane mode에 맞춰 line을 만들고 height tier·indent tier·결정론 level을 부여한다."""

    ordered_lines: list[dict[str, Any]] = []
    for pdf_page in toc_pages:
        boxes = extract_page_boxes(pdf_path, pdf_page)
        if not boxes:
            continue
        if pane_mode == 2:
            balance = page_balance(boxes)
            left_lines, right_lines = split_page_panes(boxes, balance["gutter_x"])
            # pane-local indent tier
            for pane_lines in (left_lines, right_lines):
                cuts = cluster_cut_points(
                    [ln["content_min_x"] for ln in pane_lines if not is_title_word(ln["content_text"])]
                )
                for ln in pane_lines:
                    ln["indent_tier"] = band_low_first(ln["content_min_x"], cuts)
            for ln in left_lines:
                ln["pane"] = "L"
            for ln in right_lines:
                ln["pane"] = "R"
            ordered_lines.extend(left_lines)
            ordered_lines.extend(right_lines)
        else:
            page_lines = build_lines(boxes)
            cuts = cluster_cut_points(
                [ln["content_min_x"] for ln in page_lines if not is_title_word(ln["content_text"])]
            )
            for ln in page_lines:
                ln["indent_tier"] = band_low_first(ln["content_min_x"], cuts)
                ln["pane"] = "-"
            ordered_lines.extend(page_lines)

    # height tier는 전체 line에서 한 번 구한다.
    height_cuts = cluster_cut_points(
        [ln["height"] for ln in ordered_lines if not is_title_word(ln["content_text"])],
        grid_size=2048,
    )
    for ln in ordered_lines:
        ln["height_tier"] = height_tier(ln["height"], height_cuts)

    # 결정론 level = (height_tier, indent_tier) tuple의 dense rank(작을수록 상위).
    combos = sorted({(ln["height_tier"], ln["indent_tier"]) for ln in ordered_lines})
    level_of = {combo: idx + 1 for idx, combo in enumerate(combos)}
    for line_no, ln in enumerate(ordered_lines, start=1):
        ln["line_no"] = line_no
        ln["level"] = level_of[(ln["height_tier"], ln["indent_tier"])]

    debug = {
        "line_count": len(ordered_lines),
        "height_tier_distribution": {str(k): v for k, v in sorted(Counter(l["height_tier"] for l in ordered_lines).items())},
        "indent_tier_distribution": {str(k): v for k, v in sorted(Counter(l["indent_tier"] for l in ordered_lines).items())},
        "level_distribution": {str(k): v for k, v in sorted(Counter(l["level"] for l in ordered_lines).items())},
        "level_combos": {f"H{h}I{i}": level_of[(h, i)] for (h, i) in combos},
    }
    return ordered_lines, debug


# ===========================================================================
# Stage 6: LLM structured 목차 추출 (level 마커 동봉, page 단위)
# ===========================================================================
EXTRACT_SYSTEM = (
    "너는 책 목차 page에서 항목을 structured output으로 추출하는 도구다. 각 줄은 [Ln] level 마커로 시작한다. "
    "Ln은 결정론으로 정해진 계층 level이다(작을수록 상위, 큰 글씨/얕은 들여쓰기).\n"
    "규칙:\n"
    "- level은 네가 정하지 않는다. 항목이 나온 줄의 [Ln] 숫자를 그대로 복사한다.\n"
    "- 한 줄에 'I'/'|'/'·'/'•'+페이지번호로 여러 항목이 합쳐져 있으면 각 항목으로 분리하고, 모든 조각은 그 줄의 level을 받는다.\n"
    "- printed_page: 제목 뒤(또는 구분자 뒤)의 인쇄 페이지 번호. 없으면 null.\n"
    "- title: 깨진 OCR 글씨를 의미를 바꾸지 않고 깨끗하게 복원한다. 없는 항목을 지어내지 않는다.\n"
    "- '목차'/'Contents' 같은 머리말 한 마디 줄은 항목으로 만들지 않는다.\n"
    "- source_pdf_page: 입력의 '--- PDF page N ---' 마커의 N을 그대로 쓴다.\n"
    "- 항목은 입력에 나온 순서 그대로 반환한다."
)
EXTRACT_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "toc_items",
        "schema": {
            "type": "object",
            "properties": {
                "is_toc_page": {"type": "boolean"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "level": {"type": "integer"},
                            "printed_page": {"type": ["integer", "null"]},
                            "source_pdf_page": {"type": "integer"},
                        },
                        "required": ["title", "level", "printed_page", "source_pdf_page"],
                    },
                },
            },
            "required": ["is_toc_page", "items"],
        },
    },
}


def render_page_for_extract(page_lines: list[dict[str, Any]], pdf_page: int) -> str:
    body = "\n".join(f"[L{ln['level']}] {ln['text']}" for ln in page_lines)
    return f"--- PDF page {pdf_page} ---\n{body}"


def extract_items_for_page(page_lines: list[dict[str, Any]], pdf_page: int) -> list[dict[str, Any]]:
    """한 page의 level 마커 텍스트를 LLM에 줘 structured 목차 항목을 뽑는다."""

    user = "다음 목차 page에서 항목을 추출하라.\n\n" + render_page_for_extract(page_lines, pdf_page)
    response = client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": user}],
        response_format=EXTRACT_RESPONSE_FORMAT,
        temperature=0.0,
    )
    parsed = loads_lenient(response.choices[0].message.content)
    if not parsed.get("is_toc_page", True):
        return []
    return parsed.get("items", []) or []


# ===========================================================================
# 책별 full flow 실행
# ===========================================================================
def load_targets() -> list[dict[str, Any]]:
    labels = json.loads(LABELS_JSON.read_text(encoding="utf-8"))["labels"]
    by_id = {label["id"]: label for label in labels}
    missing = [tid for tid in TARGET_IDS if tid not in by_id]
    if missing:
        raise RuntimeError(f"라벨 파일에 대상 id가 없다: {missing}")
    return [by_id[tid] for tid in TARGET_IDS]


def run_book(target: dict[str, Any]) -> dict[str, Any]:
    book_id = target["id"]
    pdf_path = ROOT_DIR / target["input_pdf"]
    result: dict[str, Any] = {"id": book_id, "input_pdf": target["input_pdf"]}
    print(f"\n{'#' * 78}\n# BOOK {book_id}\n{'#' * 78}")
    if not pdf_path.exists():
        print(f"  [SKIP] PDF 없음: {pdf_path}")
        result["status"] = "missing_pdf"
        return result

    with fitz.open(pdf_path) as document:
        total_pages = document.page_count

    # --- Stage 1: ML 기반 toc_page_range ---
    print("\n[1] ML TOC page detection")
    if not MODEL_PATH.exists():
        print(f"  [BLOCKED] 모델 artifact 없음: {MODEL_PATH}")
        result["status"] = "blocked_no_model"
        return result
    pages = extract_page_texts(pdf_path, max_pages=min(MAX_SEARCH_PAGES, total_pages))
    features = calculate_page_features(pages, total_pages)
    detection = detect_toc_pages(features, TocMlDetectionConfig(model_path=MODEL_PATH))
    print(f"  ML range = {detection.pages} (start={detection.start_page}, conf={detection.confidence:.3f}, method={detection.method})")
    result["ml_detection"] = {"pages": detection.pages, "start_page": detection.start_page, "confidence": detection.confidence}

    # --- Stage 2: LLM per-page is_toc_page 보정 ---
    # LLM은 page별 is_toc_page만 판정하고(페이지 번호 동반이 필수 요건), 멈춤은 다음 page가
    # false일 때 일어난다. is_toc_page=true면 반드시 다음 page도 LLM으로 이어간다.
    print("\n[2] LLM per-page is_toc_page scan (halt = next page=false)")
    page_text = {page.pdf_page: page.text for page in pages}
    seed_start = detection.start_page or 1
    toc_pages, anchor, toc_trace = correct_toc_range(page_text, seed_start, total_pages)
    for entry in toc_trace:
        print(
            f"  p{entry['pdf_page']}: is_toc={entry['is_toc_page']} "
            f"has_page_num={entry['has_page_numbers']} conf={entry['confidence']}"
        )
    print(f"  LLM-corrected range = {toc_pages} (anchor={anchor}, llm_calls={len(toc_trace)})")
    result["llm_range"] = {"pages": toc_pages, "anchor": anchor, "llm_calls": len(toc_trace), "trace": toc_trace}
    if not toc_pages:
        print("  [STOP] TOC range를 못 찾음")
        result["status"] = "no_toc_range"
        return result

    # --- Stage 3 & 4: per-page balance 신호 + pane vote ---
    print("\n[3,4] per-page balance signal + LLM 1/2 pane vote")
    page_votes: list[dict[str, Any]] = []
    for pdf_page in toc_pages:
        boxes = extract_page_boxes(pdf_path, pdf_page)
        if not boxes:
            continue
        balance = page_balance(boxes)
        whole = build_lines(boxes)
        left, right = split_page_panes(boxes, balance["gutter_x"])
        llm = classify_page_pane(pdf_page, balance, whole, left, right)
        pred = int(llm.get("pane_count", 0) or 0)
        page_votes.append({"pdf_page": pdf_page, "balance": balance["balance"],
                           "gutter_straddle_ratio": balance["gutter_straddle_ratio"], "pane": pred})
        print(f"  p{pdf_page}: balance={balance['balance']:.3f} straddle={balance['gutter_straddle_ratio']:.3f} -> pane={pred}")
    vote = Counter(v["pane"] for v in page_votes)
    # 한 page라도 2단이면 2단 책(037 rollup)
    pane_mode = 2 if vote.get(2, 0) > 0 else 1
    print(f"  vote = {dict(vote)} -> book pane_mode = {pane_mode}")
    result["pane"] = {"votes": page_votes, "vote_count": dict(vote), "pane_mode": pane_mode}

    # --- Stage 5: deterministic level/hierarchy ---
    print("\n[5] deterministic height/indent tier -> level")
    lines, hier_debug = build_hierarchy_lines(pdf_path, toc_pages, pane_mode)
    print(f"  lines={hier_debug['line_count']} height_tiers={hier_debug['height_tier_distribution']} "
          f"indent_tiers={hier_debug['indent_tier_distribution']}")
    print(f"  level_dist={hier_debug['level_distribution']} combos(H,I->L)={hier_debug['level_combos']}")
    result["hierarchy"] = hier_debug

    # --- Stage 6: LLM structured 목차 추출 (page 단위) ---
    print("\n[6] LLM structured TOC extraction (per-page)")
    lines_by_page: dict[int, list[dict[str, Any]]] = {}
    for ln in lines:
        lines_by_page.setdefault(ln["pdf_page"], []).append(ln)
    toc_items: list[dict[str, Any]] = []
    for pdf_page in toc_pages:
        page_lines = lines_by_page.get(pdf_page, [])
        if not page_lines:
            continue
        items = extract_items_for_page(page_lines, pdf_page)
        toc_items.extend(items)
        print(f"  p{pdf_page}: {len(items)} items")
    print(f"  total items = {len(toc_items)}")
    result["toc_item_count"] = len(toc_items)

    # --- Stage 7: deterministic offset -> bookmark ---
    print("\n[7] deterministic offset -> bookmarks")
    offset: int | None = None
    try:
        offset_est = estimate_page_offset(pdf_path, OffsetEstimationConfig())
        offset = offset_est.offset
        print(f"  offset = {offset} (printed 1 ~ PDF {1 + (offset or 0)}, conf={offset_est.confidence:.3f})")
    except OffsetEstimationError as error:
        print(f"  [WARN] offset 추정 실패: {error}")
    result["offset"] = offset

    bookmarks: list[dict[str, Any]] = []
    for item in toc_items:
        printed = item.get("printed_page")
        pdf_target = (printed + offset) if (printed is not None and offset is not None) else None
        bookmarks.append(
            {
                "title": item.get("title", "").strip(),
                "level": int(item.get("level", 1) or 1),
                "printed_page": printed,
                "pdf_page": pdf_target,
                "source_pdf_page": item.get("source_pdf_page"),
            }
        )
    placeable = sum(1 for b in bookmarks if b["pdf_page"] is not None)
    print(f"  bookmarks = {len(bookmarks)} (pdf_page 확정 {placeable})")
    result["bookmark_count"] = len(bookmarks)
    result["bookmark_placeable"] = placeable

    # 책별 dump
    book_dir = OUTPUT_DIR / book_id
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "bookmarks.json").write_text(json.dumps(bookmarks, ensure_ascii=False, indent=2), encoding="utf-8")
    with (book_dir / "bookmarks.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["level", "title", "printed_page", "pdf_page", "source_pdf_page"])
        writer.writeheader()
        for b in bookmarks:
            writer.writerow({k: b.get(k) for k in ["level", "title", "printed_page", "pdf_page", "source_pdf_page"]})
    (book_dir / "lines_with_level.json").write_text(json.dumps(lines, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  dump -> {book_dir.relative_to(ROOT_DIR)} (bookmarks.json/csv)")

    result["status"] = "ok"
    result["dump_dir"] = str(book_dir.relative_to(ROOT_DIR))
    return result


def build_finding(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for r in results:
        if r.get("status") != "ok":
            parts.append(f"{r['id']}: {r.get('status')}")
            continue
        parts.append(
            f"{r['id']}: ML={r['ml_detection']['pages']} -> LLM range={r['llm_range']['pages']}, "
            f"pane_mode={r['pane']['pane_mode']}(votes={r['pane']['vote_count']}), "
            f"levels={r['hierarchy']['level_distribution']}, items={r['toc_item_count']}, "
            f"offset={r['offset']}, bookmarks={r['bookmark_count']}(placeable={r['bookmark_placeable']})"
        )
    return (
        "TOC page 탐지(ML)->LLM per-page range 보정->per-page balance+pane vote->결정론 "
        "height/indent tier level->LLM structured 추출->offset->bookmark까지 full flow를 한 번에 이었다. "
        + " | ".join(parts)
        + " || 모든 LLM 판정은 per-page 단위이며, 책별 bookmark는 outputs에 json/csv로 dump했다."
    )


def record_experiment(summary: dict[str, Any]) -> None:
    registry = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "035~037에서 검증한 per-page pane 판정을 핵심 축으로, TOC page 탐지부터 최종 bookmark "
            "생성까지 full flow를 한 실험으로 통합한다. (1) ML TOC page detection -> (2) LLM per-page "
            "is_toc_page range 보정 -> (3) per-page 결정론 balance/gutter 신호 -> (4) LLM per-page "
            "1/2 pane vote -> (5) 결정론 height/indent tier level -> (6) level 마커 동봉 LLM structured "
            "목차 추출 -> (7) 결정론 offset 적용 bookmark. 모든 LLM 판정은 per-page 단위다."
        ),
        "inputs": [t["input_pdf"] for t in load_targets()],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": str(LABELS_JSON.relative_to(ROOT_DIR)),
        "model": MODEL,
        "temperature": 0.0,
        "finding": summary["finding"],
        "ran_at": summary["ran_at"],
    }
    registry["experiments"] = [e for e in registry["experiments"] if e.get("id") != EXPERIMENT_ID]
    registry["experiments"].append(entry)
    EXPERIMENTS_JSON.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    # 사내 프록시 self-signed CA 대응: OS 신뢰 저장소 사용.
    import truststore

    truststore.inject_into_ssl()
    load_dotenv(ROOT_DIR / ".env")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    targets = load_targets()
    results: list[dict[str, Any]] = []
    for target in targets:
        try:
            results.append(run_book(target))
        except Exception as error:  # noqa: BLE001 - 한 책 실패가 전체를 죽이지 않게 한다.
            print(f"  [ERROR] {target['id']} 처리 중 예외: {type(error).__name__}: {error}")
            results.append({"id": target["id"], "input_pdf": target["input_pdf"],
                            "status": "error", "error": f"{type(error).__name__}: {error}"})
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "model": MODEL,
        "results": results,
    }
    summary["finding"] = build_finding(results)
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    record_experiment(summary)

    print(f"\n{'=' * 78}\n=== exp 038 full flow summary ===")
    print(summary["finding"])


if __name__ == "__main__":
    main()
