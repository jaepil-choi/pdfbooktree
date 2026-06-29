"""experiment 036: 1-pane 읽기 vs 2-pane 읽기를 markdown으로 보여주고 LLM이 고른다.

배경:
- 034/035는 page 전체 y-KDE로 병합된 줄(2단이면 좌우 항목이 한 줄로 붙은)만 LLM에 주고
  "이 병합 패턴을 알아채라"고 시켰다. 탐지 난이도가 높고 LLM에 불리했다(1-pane 책을
  2-pane으로 과판정).
- 이번 실험은 같은 목차를 두 방식으로 읽어 둘 다 보여주고 더 자연스러운 쪽을 고르게 한다.
  - A안(1 pane): page를 한 단으로 보고 추출된 줄 순서대로 읽는다.
  - B안(2 pane): page를 좌우 두 단으로 보고 왼쪽 단을 위에서 아래로 다 읽은 뒤
    오른쪽 단을 읽는다.
- 진짜 2단 목차면 A안은 "왼쪽항목 + 오른쪽항목"이 한 줄에 뒤섞여 읽기가 깨지고 B안이
  매끄럽다. 진짜 1단 목차면 A안이 매끄럽고 B안은 순서가 뒤틀린다. 비교 과제라 LLM이
  잘 맞출 것으로 본다.

실행:
    uv run python experiments/036_llm_pane_ab_markdown.py
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
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
EXPERIMENT_ID = "036_llm_pane_ab_markdown"
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
# zvi(2)·quant(1)·kim_note2(1)는 사용자 확인 정답. note1·hankyung은 좌우 balance가
# 극단적(0.05 미만)이라 1-pane으로 강하게 추정되나 미확인이라 별도 표시한다.
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


def extract_textboxes(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """TOC page의 span/textbox를 page_width와 함께 추출한다."""

    boxes: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for pdf_page in toc_pages:
            if pdf_page < 1 or pdf_page > document.page_count:
                continue
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
    """box를 (page, y-row)로 묶어 읽는 순서 line으로 만든다."""

    tier_by_box = _y_tier_by_box(boxes)
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for box in boxes:
        if not box["is_content"] and not _DIGIT.search(box["text"]):
            continue
        key = (int(box["pdf_page"]), tier_by_box[id(box)])
        grouped.setdefault(key, []).append(box)

    lines: list[dict[str, Any]] = []
    for (pdf_page, y_tier), members in sorted(grouped.items()):
        ordered = sorted(members, key=lambda value: (value["x0"], value["span_index"]))
        content_members = [member for member in ordered if member["is_content"]]
        if not content_members:
            continue
        lines.append(
            {
                "pdf_page": pdf_page,
                "y_tier": y_tier,
                "text": normalize_text(" ".join(member["text"] for member in ordered)),
            }
        )
    return lines


def split_panes(boxes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """page를 좌우 half로 나눈 뒤 각 pane 내부에서 읽는 순서 line을 만든다."""

    left_boxes = [box for box in boxes if float(box["x0"]) < float(box["page_width"]) / 2]
    right_boxes = [box for box in boxes if float(box["x0"]) >= float(box["page_width"]) / 2]
    return build_lines(left_boxes), build_lines(right_boxes)


# ---------------------------------------------------------------------------
# markdown 렌더링: A안(1 pane) vs B안(2 pane)
# ---------------------------------------------------------------------------
def render_one_pane_markdown(whole_lines: list[dict[str, Any]]) -> str:
    """A안: page 전체를 한 단으로 보고 줄 순서대로 읽은 markdown."""

    body = "\n".join(f"- {line['text']}" for line in whole_lines)
    return f"## 목차 (한 단으로 읽기)\n{body}"


def render_two_pane_markdown(
    left_lines: list[dict[str, Any]], right_lines: list[dict[str, Any]]
) -> str:
    """B안: page마다 왼쪽 단을 위에서 아래로 읽은 뒤 오른쪽 단을 읽고 다음 page로 넘어간다.

    여러 page짜리 2단 목차는 page별로 좌->우를 읽어야 자연스럽다. 모든 page의 왼쪽 단을
    먼저 몰아 읽고 오른쪽 단을 나중에 몰면 같은 page의 두 단이 멀리 떨어져 읽기가 깨진다.
    """

    pages = sorted({line["pdf_page"] for line in left_lines + right_lines})
    sections: list[str] = []
    for page in pages:
        page_left = [line for line in left_lines if line["pdf_page"] == page]
        page_right = [line for line in right_lines if line["pdf_page"] == page]
        block = [f"### page {page} · 왼쪽 단"]
        block.extend(f"- {line['text']}" for line in page_left)
        block.append(f"### page {page} · 오른쪽 단")
        block.extend(f"- {line['text']}" for line in page_right)
        sections.append("\n".join(block))
    return "## 목차 (두 단으로 읽기)\n" + "\n".join(sections)


# ---------------------------------------------------------------------------
# LLM A/B 선택
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
    "너는 책 목차 page가 한 단(1 pane)인지 두 단(2 pane)인지 판정하는 도구다.\n"
    "같은 목차 page에서 추출한 같은 텍스트를 두 가지 읽기 방식으로 보여준다.\n"
    "- A안은 page를 한 단으로 보고 줄 순서대로 읽은 것이다.\n"
    "- B안은 page를 좌우 두 단으로 보고, 왼쪽 단을 위에서 아래로 다 읽은 뒤 오른쪽 단을 읽은 것이다.\n"
    "두 읽기 중 목차로서 더 자연스럽게 이어지는 쪽을 골라라.\n"
    "판단 기준: 한 줄 안에 서로 무관한 항목이 둘씩 섞여 있거나 페이지 번호가 줄 중간에 끼면 그 읽기는 깨진 것이다. "
    "각 항목이 하나씩 자연스럽게 이어지고 페이지 번호가 줄 끝에 오면 그 읽기가 옳다.\n"
    "A안이 자연스러우면 pane_count=1, B안이 자연스러우면 pane_count=2로 답하라."
)

PANE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "pane_ab_choice",
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


def build_user_message(target: dict[str, Any], md_a: str, md_b: str) -> str:
    """A안/B안 markdown을 담은 user message를 만든다."""

    return (
        f"다음은 '{Path(target['input_pdf']).stem}' 책의 목차 page를 두 방식으로 읽은 것이다. "
        "어느 읽기가 자연스러운 목차인지 고르고 pane_count를 답하라.\n\n"
        "=== A안: 한 단으로 읽기 ===\n"
        f"{md_a}\n\n"
        "=== B안: 두 단으로 읽기 ===\n"
        f"{md_b}\n"
    )


def classify_panes(target: dict[str, Any], md_a: str, md_b: str) -> dict[str, Any]:
    """LLM에 A안/B안 중 자연스러운 읽기를 고르게 한다."""

    response = client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": PANE_SYSTEM},
            {"role": "user", "content": build_user_message(target, md_a, md_b)},
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
    """한 권에 대해 A/B markdown을 만들고 LLM에 pane을 고르게 한다."""

    pdf_path = ROOT_DIR / target["input_pdf"]
    gt = GROUND_TRUTH_PANES[target["id"]]
    result: dict[str, Any] = {
        "id": target["id"],
        "input_pdf": target["input_pdf"],
        "toc_pages": target["toc_pages"],
        "ground_truth_panes": gt,
        "gt_confirmed": target["id"] in CONFIRMED_GT,
    }
    if not pdf_path.exists():
        result["status"] = "missing_pdf"
        return result

    boxes = extract_textboxes(pdf_path, target["toc_pages"])
    whole_lines = build_lines(boxes)
    left_lines, right_lines = split_panes(boxes)
    md_a = render_one_pane_markdown(whole_lines)
    md_b = render_two_pane_markdown(left_lines, right_lines)

    llm = classify_panes(target, md_a, md_b)
    predicted = int(llm.get("pane_count", 0) or 0)

    target_dir = OUTPUT_DIR / target["id"]
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "reading_A_one_pane.md").write_text(md_a, encoding="utf-8")
    (target_dir / "reading_B_two_pane.md").write_text(md_b, encoding="utf-8")
    (target_dir / "llm_response.json").write_text(
        json.dumps(llm, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    result.update(
        {
            "status": "ok",
            "whole_line_count": len(whole_lines),
            "left_line_count": len(left_lines),
            "right_line_count": len(right_lines),
            "predicted_panes": predicted,
            "chosen_reading": llm.get("chosen_reading"),
            "confidence": llm.get("confidence"),
            "reason": llm.get("reason"),
            "is_correct": predicted == gt,
        }
    )
    return result


def build_finding(results: list[dict[str, Any]]) -> str:
    """experiments.json에 남길 finding 문자열을 만든다."""

    parts: list[str] = []
    correct = 0
    confirmed_total = 0
    for result in results:
        if result.get("status") != "ok":
            parts.append(f"{result['id']}: {result.get('status')}")
            continue
        ok = result["is_correct"]
        if result["gt_confirmed"]:
            confirmed_total += 1
            correct += int(ok)
        flag = "" if result["gt_confirmed"] else "(추정GT)"
        parts.append(
            f"{result['id']}{flag}: gt={result['ground_truth_panes']} "
            f"LLM={result['predicted_panes']}(읽기 {result['chosen_reading']}) "
            f"conf={result['confidence']} correct={ok} "
            f"[whole={result['whole_line_count']} L={result['left_line_count']} R={result['right_line_count']}]"
        )
    return (
        "같은 목차를 A안(한 단 읽기)·B안(두 단 읽기) markdown으로 둘 다 보여주고 LLM이 "
        "자연스러운 쪽을 고르게 했다. "
        + " | ".join(parts)
        + f" || confirmed accuracy={correct}/{confirmed_total}. "
        "034/035의 '병합 패턴 탐지' 대신 A/B 비교 과제로 바꿔 1-pane 책 과판정이 사라지는지 확인했다."
    )


def record_experiment(summary: dict[str, Any]) -> None:
    """실험 registry에 이번 결과를 기록한다."""

    registry = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "034/035의 LLM pane gate가 2단으로 병합된 텍스트만 보여주고 병합 패턴 탐지를 "
            "시켜 1-pane 책을 2-pane으로 과판정한 문제를, 같은 목차를 A안(page 전체 한 단 "
            "읽기)과 B안(좌우 두 단으로 왼쪽 먼저 오른쪽 나중 읽기) 두 markdown으로 둘 다 "
            "보여주고 LLM이 더 자연스러운 읽기를 고르는 A/B 비교 과제로 바꿔 해결한다."
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

    print("=== exp 036: LLM pane A/B markdown choice ===")
    for result in results:
        if result.get("status") != "ok":
            print(f"- {result['id']}: {result.get('status')}")
            continue
        print(
            f"- {result['id']}: gt={result['ground_truth_panes']}"
            f"{'' if result['gt_confirmed'] else '(추정)'} "
            f"pred={result['predicted_panes']} reading={result['chosen_reading']} "
            f"conf={result['confidence']} correct={result['is_correct']}"
        )
        print(f"    reason={result['reason']}")
    print(summary["finding"])


if __name__ == "__main__":
    main()
