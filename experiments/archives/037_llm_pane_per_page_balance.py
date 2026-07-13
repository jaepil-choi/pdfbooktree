"""experiment 037: page 단위로 balance 힌트를 주고 문장 연결성으로 1/2 pane을 고른다.

배경:
- 036에서 같은 목차를 A안(한 단 읽기)·B안(두 단 읽기) markdown으로 보여주고 고르게 하니
  034/035의 1-pane 과판정이 대부분 사라졌다(4/5). 남은 오답 kim_note2는 1단 목차인데
  긴 줄이 page 중앙을 넘어가 width/2 split이 가짜 오른쪽 단(꼬리 조각)을 만들어 LLM이
  B를 자연스럽다고 본 케이스였다.
- 이번 실험은 네 가지를 바꾼다.
  (1) page 단위로 판정한다. pane 구조는 책 전체가 아니라 page의 속성이다.
  (2) LLM에게 결정론 좌우 balance 신호를 보조 힌트로 같이 준다.
  (3) 질문을 "어느 읽기에서 각 항목의 문장이 끊기지 않고 이어지는가"로 바꾼다.
      1단 page를 억지로 2단으로 나누면 한 줄이 좌우로 잘려 문장이 조각난다.
  (4) split을 width/2 고정이 아니라 검출한 gutter(중앙 빈 띠)에서 한다. width/2는 칼럼
      경계 box를 오배치해 진짜 2단 page의 B에 'page번호 누수'나 wrap 제목 분리 조각을
      만들어 LLM이 B를 깨졌다고 보게 했다. gutter 깨끗함(straddle_ratio)도 힌트로 준다.

실행:
    uv run python experiments/037_llm_pane_per_page_balance.py
"""

from __future__ import annotations

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

from pdfbooktree.utils.text_normalize import normalize_text

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "037_llm_pane_per_page_balance"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
LABELS_JSON = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
MODEL = "solar-pro3"

TARGET_IDS = [
    "zvi_bodie_investments",
    "quant_world",
    "kim_econometrics_note1",
    "kim_econometrics_note2",
    "hankyung_reader",
]
# page 단위 정답: zvi는 모든 TOC page가 2단(per-page balance 0.74~1.0 확인),
# 나머지는 모두 1단(quant·kim_note2는 사용자 확인, note1·hankyung은 balance<0.05로 추정).
GROUND_TRUTH_PANES: dict[str, int] = {
    "zvi_bodie_investments": 2,
    "quant_world": 1,
    "kim_econometrics_note1": 1,
    "kim_econometrics_note2": 1,
    "hankyung_reader": 1,
}
CONFIRMED_GT = {"zvi_bodie_investments", "quant_world", "kim_econometrics_note2"}

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_DIGIT = re.compile(r"\d")
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def is_content_text(text: str) -> bool:
    """목차 항목 내용으로 볼 수 있는 글자 span인지 판정한다."""

    stripped = text.strip()
    return bool(stripped and (_HANGUL.search(stripped) or _LATIN2.search(stripped)))


def cluster_cut_points(
    values: list[float],
    *,
    bandwidth: float | None = None,
    grid_size: int = 2048,
) -> list[float]:
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
    peak_idx = [
        index
        for index in range(1, len(density) - 1)
        if density[index - 1] < density[index] > density[index + 1]
    ]
    if not peak_idx:
        return []
    valley_idx = [
        index
        for index in range(1, len(density) - 1)
        if density[index - 1] > density[index] < density[index + 1]
    ]
    peaks = [float(grid[index]) for index in peak_idx]
    return sorted(
        float(grid[index])
        for index in valley_idx
        if min(peaks) < float(grid[index]) < max(peaks)
    )


def band_low_first(value: float, cuts: list[float]) -> int:
    """작은 값이 1번이 되도록 1D band를 부여한다."""

    band = 1
    for cut in sorted(cuts):
        if value < cut:
            return band
        band += 1
    return band


def extract_page_boxes(pdf_path: Path, pdf_page: int) -> list[dict[str, Any]]:
    """한 page의 span/textbox를 page_width와 함께 추출한다."""

    boxes: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        if pdf_page < 1 or pdf_page > document.page_count:
            return boxes
        page = document.load_page(pdf_page - 1)
        page_width = float(page.rect.width)
        for block_index, block in enumerate(page.get_text("dict")["blocks"]):
            for line_index, line in enumerate(block.get("lines", [])):
                for span_index, span in enumerate(line.get("spans", [])):
                    text = normalize_text(span["text"])
                    if not text.strip():
                        continue
                    x0, y0, x1, y1 = [float(value) for value in span["bbox"]]
                    boxes.append(
                        {
                            "pdf_page": pdf_page,
                            "page_width": round(page_width, 2),
                            "block_index": block_index,
                            "line_index": line_index,
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
    """주어진 box 묶음 안에서 y-KDE로 row tier를 부여한다."""

    content_boxes = [box for box in boxes if box["is_content"]]
    median_span_height = (
        float(np.median([box["span_height"] for box in content_boxes]))
        if content_boxes
        else 4.0
    )
    y_bandwidth = max(1.0, median_span_height * 0.3)
    y_cuts = cluster_cut_points(
        [box["y0"] for box in content_boxes],
        bandwidth=y_bandwidth,
        grid_size=8192,
    )
    return {id(box): band_low_first(box["y0"], y_cuts) for box in boxes}


def build_lines(boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """box를 y-row로 묶어 읽는 순서 line으로 만든다(단일 page 가정)."""

    tier_by_box = _y_tier_by_box(boxes)
    grouped: dict[int, list[dict[str, Any]]] = {}
    for box in boxes:
        if not box["is_content"] and not _DIGIT.search(box["text"]):
            continue
        grouped.setdefault(tier_by_box[id(box)], []).append(box)

    lines: list[dict[str, Any]] = []
    for y_tier, members in sorted(grouped.items()):
        ordered = sorted(members, key=lambda value: (value["x0"], value["span_index"]))
        if not any(member["is_content"] for member in ordered):
            continue
        lines.append(
            {
                "y_tier": y_tier,
                "text": normalize_text(" ".join(member["text"] for member in ordered)),
            }
        )
    return lines


def detect_gutter(content_boxes: list[dict[str, Any]], page_width: float) -> dict[str, Any]:
    """중앙 band에서 content box가 가장 적게 가로지르는 x를 gutter로 검출한다.

    진짜 2단 page는 좌우 칼럼 사이에 세로 빈 띠가 있어 그 x를 가로지르는 box가 거의 없다.
    1단 page(긴 줄이 중앙을 넘어감)는 어느 중앙 x를 잡아도 가로지르는 줄이 많다.
    가로지름 최소값을 줄 수로 정규화한 straddle_ratio가 gutter 깨끗함을 나타낸다.
    """

    if not content_boxes or page_width <= 0:
        return {"gutter_x": round(page_width / 2, 2), "min_straddle": 0, "straddle_ratio": 0.0}
    low, high = 0.30 * page_width, 0.70 * page_width
    grid = np.linspace(low, high, 241)
    straddle = np.array(
        [sum(1 for box in content_boxes if box["x0"] < cx < box["x1"]) for cx in grid]
    )
    min_straddle = int(straddle.min())
    # 가로지름이 최소인 구간(빈 띠)의 가운데를 gutter로 잡는다.
    gutter_x = float(np.median(grid[straddle == straddle.min()]))
    n_rows = len(set(_y_tier_by_box(content_boxes).values())) or 1
    return {
        "gutter_x": round(gutter_x, 2),
        "min_straddle": min_straddle,
        "straddle_ratio": round(min_straddle / n_rows, 3),
    }


def page_balance(boxes: list[dict[str, Any]]) -> dict[str, Any]:
    """검출한 gutter 기준 좌우 balance, shared-row 비율, gutter 깨끗함을 계산한다."""

    content = [box for box in boxes if box["is_content"]]
    page_width = float(boxes[0]["page_width"]) if boxes else 0.0
    gutter = detect_gutter(content, page_width)
    gutter_x = gutter["gutter_x"]

    def side_of(box: dict[str, Any]) -> str:
        return "L" if (box["x0"] + box["x1"]) / 2 < gutter_x else "R"

    left = sum(1 for box in content if side_of(box) == "L")
    right = len(content) - left
    balance = round(min(left, right) / max(left, right), 3) if left and right else 0.0

    tier_by_box = _y_tier_by_box(boxes)
    rows: dict[int, set[str]] = {}
    for box in content:
        rows.setdefault(tier_by_box[id(box)], set()).add(side_of(box))
    shared = sum(1 for sides in rows.values() if sides == {"L", "R"})
    shared_pct = round(shared / len(rows), 3) if rows else 0.0
    return {
        "left_content": left,
        "right_content": right,
        "balance": balance,
        "shared_row_pct": shared_pct,
        "gutter_x": gutter_x,
        "gutter_straddle_ratio": gutter["straddle_ratio"],
    }


def split_page_panes(
    boxes: list[dict[str, Any]], gutter_x: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """검출한 gutter_x 기준 box 중심점으로 좌우 단을 나눠 각 단의 읽는 순서 line을 만든다."""

    left_boxes = [box for box in boxes if (box["x0"] + box["x1"]) / 2 < gutter_x]
    right_boxes = [box for box in boxes if (box["x0"] + box["x1"]) / 2 >= gutter_x]
    return build_lines(left_boxes), build_lines(right_boxes)


# ---------------------------------------------------------------------------
# markdown 렌더링
# ---------------------------------------------------------------------------
def render_reading_a(whole_lines: list[dict[str, Any]]) -> str:
    """A안: page를 한 단으로 보고 줄 순서대로 읽는다."""

    body = "\n".join(f"- {line['text']}" for line in whole_lines)
    return f"## reading A (한 단으로 읽기)\n{body}"


def render_reading_b(left_lines: list[dict[str, Any]], right_lines: list[dict[str, Any]]) -> str:
    """B안: 왼쪽 단을 위에서 아래로 읽은 뒤 오른쪽 단을 읽는다."""

    left_body = "\n".join(f"- {line['text']}" for line in left_lines)
    right_body = "\n".join(f"- {line['text']}" for line in right_lines)
    return (
        "## reading B (두 단으로 나눠 왼쪽 먼저, 오른쪽 나중에 읽기)\n"
        "### 왼쪽 단\n"
        f"{left_body}\n"
        "### 오른쪽 단\n"
        f"{right_body}"
    )


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
_CLIENT: Any = None


def client() -> Any:
    """Upstage 호환 OpenAI client를 만든다."""

    global _CLIENT
    if _CLIENT is None:
        from openai import OpenAI

        api_key = os.environ.get("UPSTAGE_API_KEY")
        if not api_key:
            raise RuntimeError("UPSTAGE_API_KEY가 설정되지 않았다.")
        _CLIENT = OpenAI(api_key=api_key, base_url=UPSTAGE_BASE_URL)
    return _CLIENT


def loads_lenient(content: str | None) -> dict[str, Any]:
    """LLM JSON 응답을 느슨하게 읽는다."""

    if not content:
        return {}
    text = content.strip()
    for candidate in (text, (_FENCE.search(text).group(1) if _FENCE.search(text) else None)):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}


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
        "name": "pane_per_page_choice",
        "schema": {
            "type": "object",
            "properties": {
                "chosen_reading": {"type": "string", "enum": ["A", "B"]},
                "pane_count": {"type": "integer"},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["chosen_reading", "pane_count", "confidence", "reason"],
        },
    },
}


def build_user_message(
    target: dict[str, Any], pdf_page: int, balance: dict[str, Any], md_a: str, md_b: str
) -> str:
    """balance 힌트와 A/B 읽기를 담은 user message를 만든다."""

    return (
        f"책 '{Path(target['input_pdf']).stem}'의 목차 page {pdf_page}이다.\n"
        "어느 읽기에서 각 항목의 문장이 끊기지 않고 이어지는지 보고 pane_count를 답하라.\n\n"
        "[결정론 보조 신호]\n"
        f"- 좌우 content balance = {balance['balance']} "
        f"(left={balance['left_content']}, right={balance['right_content']}, gutter_x={balance['gutter_x']})\n"
        f"- shared_row_pct = {balance['shared_row_pct']}\n"
        f"- gutter_straddle_ratio = {balance['gutter_straddle_ratio']}\n\n"
        f"{md_a}\n\n"
        f"{md_b}\n"
    )


def classify_page(
    target: dict[str, Any], pdf_page: int, balance: dict[str, Any], md_a: str, md_b: str
) -> dict[str, Any]:
    """LLM에 한 page의 pane 수를 문장 연결성으로 고르게 한다."""

    response = client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": PANE_SYSTEM},
            {"role": "user", "content": build_user_message(target, pdf_page, balance, md_a, md_b)},
        ],
        response_format=PANE_RESPONSE_FORMAT,
        temperature=0.0,
    )
    parsed = loads_lenient(response.choices[0].message.content)
    parsed["raw_content"] = response.choices[0].message.content
    return parsed


# ---------------------------------------------------------------------------
# 실행과 기록
# ---------------------------------------------------------------------------
def load_targets() -> list[dict[str, Any]]:
    """수동 정답 라벨 파일에서 이번 대상을 읽는다."""

    labels = json.loads(LABELS_JSON.read_text(encoding="utf-8"))["labels"]
    by_id = {label["id"]: label for label in labels}
    missing = [target_id for target_id in TARGET_IDS if target_id not in by_id]
    if missing:
        raise RuntimeError(f"라벨 파일에 대상 id가 없다: {missing}")
    return [by_id[target_id] for target_id in TARGET_IDS]


def run_one(target: dict[str, Any]) -> dict[str, Any]:
    """한 권의 TOC page를 page 단위로 판정한다."""

    pdf_path = ROOT_DIR / target["input_pdf"]
    gt = GROUND_TRUTH_PANES[target["id"]]
    result: dict[str, Any] = {
        "id": target["id"],
        "input_pdf": target["input_pdf"],
        "toc_pages": target["toc_pages"],
        "page_ground_truth_panes": gt,
        "gt_confirmed": target["id"] in CONFIRMED_GT,
    }
    if not pdf_path.exists():
        result["status"] = "missing_pdf"
        return result

    target_dir = OUTPUT_DIR / target["id"]
    target_dir.mkdir(parents=True, exist_ok=True)

    page_results: list[dict[str, Any]] = []
    for pdf_page in target["toc_pages"]:
        boxes = extract_page_boxes(pdf_path, pdf_page)
        if not boxes:
            page_results.append({"pdf_page": pdf_page, "status": "empty"})
            continue
        whole_lines = build_lines(boxes)
        balance = page_balance(boxes)
        left_lines, right_lines = split_page_panes(boxes, balance["gutter_x"])
        md_a = render_reading_a(whole_lines)
        md_b = render_reading_b(left_lines, right_lines)
        llm = classify_page(target, pdf_page, balance, md_a, md_b)
        predicted = int(llm.get("pane_count", 0) or 0)

        page_dir = target_dir / f"page_{pdf_page:03d}"
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "reading_A.md").write_text(md_a, encoding="utf-8")
        (page_dir / "reading_B.md").write_text(md_b, encoding="utf-8")
        (page_dir / "llm_response.json").write_text(
            json.dumps(llm, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        page_results.append(
            {
                "pdf_page": pdf_page,
                "status": "ok",
                "balance": balance,
                "predicted_panes": predicted,
                "chosen_reading": llm.get("chosen_reading"),
                "confidence": llm.get("confidence"),
                "reason": llm.get("reason"),
                "is_correct": predicted == gt,
            }
        )

    ok_pages = [page for page in page_results if page.get("status") == "ok"]
    predicted_counts = Counter(page["predicted_panes"] for page in ok_pages)
    # 책 단위 rollup: 2단으로 판정된 page가 하나라도 있으면 2단 책으로 본다.
    book_pred = 2 if any(page["predicted_panes"] == 2 for page in ok_pages) else 1
    correct_pages = sum(1 for page in ok_pages if page["is_correct"])
    result.update(
        {
            "status": "ok",
            "page_count": len(ok_pages),
            "page_correct": correct_pages,
            "predicted_pane_distribution": {str(k): v for k, v in sorted(predicted_counts.items())},
            "book_predicted_panes": book_pred,
            "book_correct": book_pred == gt,
            "pages": page_results,
        }
    )
    return result


def build_finding(results: list[dict[str, Any]]) -> str:
    """experiments.json에 남길 finding 문자열을 만든다."""

    parts: list[str] = []
    confirmed_pages_correct = 0
    confirmed_pages_total = 0
    for result in results:
        if result.get("status") != "ok":
            parts.append(f"{result['id']}: {result.get('status')}")
            continue
        if result["gt_confirmed"]:
            confirmed_pages_total += result["page_count"]
            confirmed_pages_correct += result["page_correct"]
        flag = "" if result["gt_confirmed"] else "(추정GT)"
        balances = [page["balance"]["balance"] for page in result["pages"] if page.get("status") == "ok"]
        parts.append(
            f"{result['id']}{flag}: page_gt={result['page_ground_truth_panes']} "
            f"page정답={result['page_correct']}/{result['page_count']} "
            f"pred분포={result['predicted_pane_distribution']} "
            f"book판정={result['book_predicted_panes']}({'O' if result['book_correct'] else 'X'}) "
            f"balance범위=[{min(balances):.2f}~{max(balances):.2f}]"
        )
    return (
        "page 단위로 검출 gutter에서 split하고 balance+gutter_straddle 힌트를 같이 주며 "
        "'어느 읽기에서 문장이 이어지는가'로 1/2 pane을 골랐다. "
        + " | ".join(parts)
        + f" || confirmed page accuracy={confirmed_pages_correct}/{confirmed_pages_total}. "
        "width/2 split이 칼럼 경계 box를 오배치해 2단 page의 B를 더럽히던 문제를 gutter split이 "
        "정리해 zvi per-page 안정성이 올라가는지, 1단 책은 100% 유지되는지 확인했다."
    )


def record_experiment(summary: dict[str, Any]) -> None:
    """실험 registry에 이번 결과를 기록한다."""

    registry = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "036의 책 단위 A/B 판정에서 남은 오답(kim_note2: 1단 긴 줄이 width/2 split으로 "
            "가짜 2단이 되어 깨짐)을 잡기 위해, page 단위로 판정하고 결정론 좌우 balance를 "
            "보조 힌트로 같이 주며, 질문을 '어느 읽기에서 각 항목 문장이 끊기지 않고 이어지는가'로 "
            "바꾼다. 또한 split을 width/2 고정이 아니라 검출한 gutter(중앙 빈 띠)에서 수행해 "
            "칼럼 경계 box 오배치로 2단 page의 B가 더러워지던 문제를 없애고 gutter_straddle_ratio를 "
            "힌트로 추가한다. reading A=page를 한 단으로, reading B=좌우 두 단으로 왼쪽 먼저 오른쪽 나중에."
        ),
        "inputs": [target["input_pdf"] for target in load_targets()],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": str(LABELS_JSON.relative_to(ROOT_DIR)),
        "model": MODEL,
        "temperature": 0.0,
        "finding": summary["finding"],
        "ran_at": summary["ran_at"],
    }
    registry["experiments"] = [
        experiment
        for experiment in registry["experiments"]
        if experiment.get("id") != EXPERIMENT_ID
    ]
    registry["experiments"].append(entry)
    EXPERIMENTS_JSON.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    """실험 entrypoint."""

    # 사내 프록시가 TLS를 가로채 self-signed CA를 끼우는 환경이라
    # certifi 번들 대신 OS(윈도우) 신뢰 저장소를 쓰도록 주입한다.
    import truststore

    truststore.inject_into_ssl()
    load_dotenv(ROOT_DIR / ".env")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = load_targets()
    results = [run_one(target) for target in targets]
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "model": MODEL,
        "temperature": 0.0,
        "results": results,
    }
    summary["finding"] = build_finding(results)
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_experiment(summary)

    print("=== exp 037: per-page pane choice with balance hint ===")
    for result in results:
        if result.get("status") != "ok":
            print(f"- {result['id']}: {result.get('status')}")
            continue
        print(
            f"- {result['id']}: page_gt={result['page_ground_truth_panes']}"
            f"{'' if result['gt_confirmed'] else '(추정)'} "
            f"page정답={result['page_correct']}/{result['page_count']} "
            f"pred={result['predicted_pane_distribution']} "
            f"book={result['book_predicted_panes']}({'O' if result['book_correct'] else 'X'})"
        )
        for page in result["pages"]:
            if page.get("status") != "ok":
                continue
            print(
                f"    p{page['pdf_page']}: pred={page['predicted_panes']} "
                f"read={page['chosen_reading']} bal={page['balance']['balance']} "
                f"conf={page['confidence']} {'O' if page['is_correct'] else 'X'}"
            )
    print(summary["finding"])


if __name__ == "__main__":
    main()
