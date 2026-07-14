"""experiment 035: LLM이 pane 수를 먼저 판정하고, 2단이면 pane별로 indent tier를 나눈다.

목적:
- 032에서 line content_min_x를 page 전체 KDE valley로 묶어 indent tier를 만들려 했지만
  Zvi Bodie 같은 double pane 목차에서 실패했다. 좌우 column이 같은 y row로 합쳐지고
  좌/우 pane의 들여쓰기 좌표가 한 분포로 섞여 x KDE valley가 의미를 잃었다
  (032 zvi: x_cuts_content=1, indent_content={'1':342,'2':81}).
- 034에서 LLM이 height tier만 보고도 1 pane / 2 pane을 정확히 갈랐다(2/2).
- 이번 실험은 그 둘을 잇는다. 먼저 034 방식 LLM gate로 pane 수를 판정하고,
  2 pane이면 page를 좌우 half로 나눠 pane 내부에서 y-KDE로 line을 만든 뒤
  pane-local content_min_x KDE valley로 indent tier를 부여한다.
  1 pane이면 032의 page 전체 경로를 그대로 쓴다.
- baseline(page 전체 indent) 대비 pane-gated indent가 2단 목차의 들여쓰기를
  복원하면서 1단 목차를 망가뜨리지 않는지 본다.

실행:
    uv run python experiments/035_llm_pane_gated_indent_tier.py
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

from pdfbooktree.utils.text_normalize import normalize_for_match, normalize_text

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "035_llm_pane_gated_indent_tier"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
LABELS_JSON = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
MODEL = "solar-pro3"

# 034에서 confident하게 확인한 pane 정답만 둔다. None은 LLM 판정만 관찰한다.
TARGET_IDS = [
    "zvi_bodie_investments",
    "quant_world",
    "kim_econometrics_note1",
    "kim_econometrics_note2",
    "hankyung_reader",
]
GROUND_TRUTH_PANES: dict[str, int | None] = {
    "zvi_bodie_investments": 2,
    "quant_world": 1,
    "kim_econometrics_note1": None,
    "kim_econometrics_note2": None,
    "hankyung_reader": None,
}

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_DIGIT = re.compile(r"\d")
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_TITLE_WORDS = {
    "목차",
    "목 차",
    "차례",
    "contents",
    "contents in brief",
    "brief contents",
    "table of contents",
}


# ---------------------------------------------------------------------------
# 텍스트 판정과 1D KDE 도구
# ---------------------------------------------------------------------------
def is_content_text(text: str) -> bool:
    """목차 항목 내용으로 볼 수 있는 글자 span인지 판정한다."""

    stripped = text.strip()
    return bool(stripped and (_HANGUL.search(stripped) or _LATIN2.search(stripped)))


def is_title_word(text: str) -> bool:
    """목차 머리말 단독 줄인지 판정한다."""

    return normalize_for_match(text) in _TITLE_WORDS


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


def height_tier(height: float, cuts: list[float]) -> int:
    """큰 글씨가 T1이 되도록 height tier를 부여한다."""

    tier = 1
    for cut in sorted(cuts, reverse=True):
        if height >= cut:
            return tier
        tier += 1
    return tier


# ---------------------------------------------------------------------------
# textbox 추출
# ---------------------------------------------------------------------------
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


def _y_tier_by_box(
    boxes: list[dict[str, Any]],
) -> dict[int, int]:
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


def _build_lines(
    boxes: list[dict[str, Any]],
    *,
    pane: str,
) -> list[dict[str, Any]]:
    """한 pane(또는 page 전체) box를 y tier로 묶어 line으로 만든다."""

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
                "pane": pane,
                "y_tier": y_tier,
                "text": normalize_text(" ".join(member["text"] for member in ordered)),
                "content_text": normalize_text(
                    " ".join(member["text"] for member in content_members)
                ),
                "content_min_x": round(min(m["x0"] for m in content_members), 2),
                "height": round(max(m["span_height"] for m in content_members), 2),
                "box_count": len(ordered),
                "content_box_count": len(content_members),
            }
        )
    return lines


def _assign_indent_tier(lines: list[dict[str, Any]]) -> list[float]:
    """주어진 line 묶음의 content_min_x로 indent tier를 부여하고 cut을 반환한다."""

    cuts = cluster_cut_points(
        [line["content_min_x"] for line in lines if not is_title_word(line["content_text"])]
    )
    for line in lines:
        line["indent_tier"] = band_low_first(line["content_min_x"], cuts)
    return cuts


def _assign_height_tier(lines: list[dict[str, Any]]) -> None:
    """line 묶음의 height로 height tier를 부여한다."""

    height_cuts = cluster_cut_points(
        [line["height"] for line in lines if not is_title_word(line["content_text"])],
        grid_size=2048,
    )
    for line in lines:
        line["height_tier"] = height_tier(line["height"], height_cuts)


def reconstruct_whole_page(boxes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """page 전체 y-KDE로 line을 만들고 page 전체 indent tier를 부여한다(032 baseline)."""

    lines = _build_lines(boxes, pane="full")
    indent_cuts = _assign_indent_tier(lines)
    _assign_height_tier(lines)
    for line_no, line in enumerate(lines, start=1):
        line["line_no"] = line_no
    debug = {
        "line_count": len(lines),
        "indent_cuts": [round(value, 2) for value in indent_cuts],
        "indent_distribution": _tier_distribution(lines, "indent_tier"),
        "height_tier_distribution": _tier_distribution(lines, "height_tier"),
    }
    return lines, debug


def reconstruct_pane_gated(boxes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """좌우 half pane별로 y-KDE line을 만들고 pane-local indent tier를 부여한다."""

    partitions: dict[str, list[dict[str, Any]]] = {"left": [], "right": []}
    for box in boxes:
        pane = "left" if float(box["x0"]) < float(box["page_width"]) / 2 else "right"
        partitions[pane].append(box)

    lines: list[dict[str, Any]] = []
    pane_debug: dict[str, Any] = {}
    for pane in ["left", "right"]:
        pane_lines = _build_lines(partitions[pane], pane=pane)
        indent_cuts = _assign_indent_tier(pane_lines)
        pane_debug[pane] = {
            "line_count": len(pane_lines),
            "indent_cuts": [round(value, 2) for value in indent_cuts],
            "indent_distribution": _tier_distribution(pane_lines, "indent_tier"),
        }
        lines.extend(pane_lines)

    _assign_height_tier(lines)
    # 읽는 순서: 왼쪽 pane을 위에서 아래로 다 읽고 오른쪽 pane으로 넘어간다.
    lines.sort(key=lambda line: (line["pdf_page"], 0 if line["pane"] == "left" else 1, line["y_tier"]))
    for line_no, line in enumerate(lines, start=1):
        line["line_no"] = line_no
    debug = {
        "line_count": len(lines),
        "panes": pane_debug,
        "indent_distribution": _tier_distribution(lines, "indent_tier"),
        "height_tier_distribution": _tier_distribution(lines, "height_tier"),
    }
    return lines, debug


def _tier_distribution(lines: list[dict[str, Any]], key: str) -> dict[str, int]:
    """tier 분포를 문자열 key dict로 만든다."""

    return {
        str(tier): count
        for tier, count in sorted(Counter(line[key] for line in lines).items())
    }


def preview_by_indent(lines: list[dict[str, Any]]) -> dict[str, list[str]]:
    """indent tier별 대표 line을 pane 표시와 함께 몇 개만 뽑는다."""

    out: dict[str, list[str]] = {}
    for line in lines:
        if is_title_word(line["content_text"]):
            continue
        tier = str(line["indent_tier"])
        out.setdefault(tier, [])
        if len(out[tier]) < 6:
            tag = f"[{line['pane'][0]}]" if line["pane"] != "full" else ""
            out[tier].append(f"{tag}{line['content_text'][:90]}")
    return out


# ---------------------------------------------------------------------------
# LLM pane gate (034 재사용)
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
    "너는 책 목차 page의 pane 구조를 판정하는 도구다. 입력에는 각 줄의 text와 height_tier만 있다. "
    "x 좌표, x bin, indent, column 정보는 제공되지 않는다.\n"
    "height_tier는 T1이 가장 큰 글씨다. 이 신호는 제목/항목 구분 보조용이지 pane 개수의 직접 증거는 아니다.\n"
    "판정 기준:\n"
    "- 2 pane 목차는 같은 y row의 좌우 항목이 한 줄로 붙어 보일 수 있다. 그래서 한 줄 안에 서로 독립적인 목차 항목이 둘 이상 있거나, 제목-페이지번호 패턴이 반복되거나, 의미가 갑자기 다른 항목이 이어지는 일이 많다.\n"
    "- 1 pane 목차는 줄마다 하나의 항목이 자연스럽게 이어지고, page 번호가 보통 줄 끝에 한 번 나타난다.\n"
    "- 단순히 글씨 크기 tier가 여러 개라는 이유만으로 2 pane이라고 하지 마라.\n"
    "반드시 pane_count를 1 또는 2로만 답하라."
)

PANE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "pane_classification",
        "schema": {
            "type": "object",
            "properties": {
                "pane_count": {"type": "integer"},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
                "evidence_line_numbers": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
            },
            "required": ["pane_count", "confidence", "reason", "evidence_line_numbers"],
        },
    },
}


def build_pane_payload(target: dict[str, Any], lines: list[dict[str, Any]], debug: dict[str, Any]) -> dict[str, Any]:
    """좌표/indent 없이 height tier만 담은 pane gate payload를 만든다."""

    llm_lines = [
        {
            "line_no": line["line_no"],
            "pdf_page": line["pdf_page"],
            "height_tier": line["height_tier"],
            "text": line["text"],
        }
        for line in lines
    ]
    return {
        "book_id": target["id"],
        "title_from_filename": Path(target["input_pdf"]).stem,
        "toc_pages": target["toc_pages"],
        "signal_contract": {
            "height_tier": "T1이 가장 큰 글씨다.",
            "x_bin": "제공하지 않음",
        },
        "line_count": len(llm_lines),
        "height_tier_distribution": debug["height_tier_distribution"],
        "lines": llm_lines,
    }


def classify_panes(payload: dict[str, Any]) -> dict[str, Any]:
    """LLM에 pane 판정을 요청한다."""

    response = client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": PANE_SYSTEM},
            {
                "role": "user",
                "content": "다음 목차 line payload로 pane_count를 판정하라.\n"
                + json.dumps(payload, ensure_ascii=False, indent=2),
            },
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
    """한 권에 대해 pane gate -> pane별 indent tier를 수행한다."""

    pdf_path = ROOT_DIR / target["input_pdf"]
    result: dict[str, Any] = {
        "id": target["id"],
        "input_pdf": target["input_pdf"],
        "toc_pages": target["toc_pages"],
        "ground_truth_panes": GROUND_TRUTH_PANES.get(target["id"]),
    }
    if not pdf_path.exists():
        result["status"] = "missing_pdf"
        return result

    boxes = extract_textboxes(pdf_path, target["toc_pages"])

    # 1) page 전체 line으로 LLM pane gate (034와 동일 입력)
    whole_lines, whole_debug = reconstruct_whole_page(boxes)
    pane_payload = build_pane_payload(target, whole_lines, whole_debug)
    llm = classify_panes(pane_payload)
    predicted_panes = int(llm.get("pane_count", 0) or 0)

    # 2) pane gate 결과에 따라 indent tier 경로 선택
    if predicted_panes == 2:
        gated_lines, gated_debug = reconstruct_pane_gated(boxes)
        route = "pane_gated_half"
    else:
        gated_lines, gated_debug = whole_lines, whole_debug
        route = "whole_page"

    target_dir = OUTPUT_DIR / target["id"]
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "pane_payload.json").write_text(
        json.dumps(pane_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (target_dir / "llm_pane_response.json").write_text(
        json.dumps(llm, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (target_dir / "baseline_whole_lines.json").write_text(
        json.dumps(whole_lines, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (target_dir / "gated_lines.json").write_text(
        json.dumps(gated_lines, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    gt = GROUND_TRUTH_PANES.get(target["id"])
    result.update(
        {
            "status": "ok",
            "predicted_panes": predicted_panes,
            "pane_confidence": llm.get("confidence"),
            "pane_reason": llm.get("reason"),
            "is_pane_correct": (gt == predicted_panes) if gt is not None else None,
            "route": route,
            "baseline_whole": {
                "line_count": whole_debug["line_count"],
                "indent_cuts": whole_debug["indent_cuts"],
                "indent_distribution": whole_debug["indent_distribution"],
                "preview": preview_by_indent(whole_lines),
            },
            "gated": {
                "line_count": gated_debug["line_count"],
                "indent_distribution": gated_debug["indent_distribution"],
                "panes": gated_debug.get("panes"),
                "preview": preview_by_indent(gated_lines),
            },
        }
    )
    return result


def build_finding(results: list[dict[str, Any]]) -> str:
    """experiments.json에 남길 finding 문자열을 만든다."""

    parts: list[str] = []
    correct = 0
    total = 0
    for result in results:
        if result.get("status") != "ok":
            parts.append(f"{result['id']}: {result.get('status')}")
            continue
        if result["is_pane_correct"] is not None:
            total += 1
            correct += int(result["is_pane_correct"])
        gated_panes = result["gated"].get("panes")
        pane_cuts = (
            f"L cuts={gated_panes['left']['indent_cuts']} R cuts={gated_panes['right']['indent_cuts']}"
            if gated_panes
            else "(whole page)"
        )
        parts.append(
            f"{result['id']}: gt={result['ground_truth_panes']} LLM={result['predicted_panes']}pane "
            f"conf={result['pane_confidence']} route={result['route']}, "
            f"baseline_indent={result['baseline_whole']['indent_distribution']} "
            f"(cuts={result['baseline_whole']['indent_cuts']}), "
            f"gated_indent={result['gated']['indent_distribution']} [{pane_cuts}]"
        )
    return (
        f"LLM pane gate(2/2 known={correct}/{total}) 후 2단이면 pane별 indent tier를 분리했다. "
        + " | ".join(parts)
        + " || 핵심 비교: Zvi Bodie(2 pane)는 032 baseline에서 좌우 column이 섞여 indent tier가 "
        "붕괴했는데, pane-gated half split이 좌/우 pane 각각 안에서 들여쓰기 tier를 복원하는지, "
        "1 pane 책들은 whole_page 경로로 그대로 유지되는지 확인한다."
    )


def record_experiment(summary: dict[str, Any]) -> None:
    """실험 registry에 이번 결과를 기록한다."""

    registry = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "032의 page 전체 content_min_x KDE indent tier가 Zvi Bodie 같은 double pane에서 "
            "좌우 column이 섞여 실패한 문제를, 034 LLM pane gate로 먼저 1/2 pane을 판정한 뒤 "
            "2 pane이면 page를 좌우 half로 나눠 pane 내부에서 y-KDE line을 만들고 "
            "pane-local content_min_x KDE valley로 indent tier를 부여하는 방식으로 푼다. "
            "1 pane이면 032의 page 전체 경로를 유지한다. baseline(page 전체 indent)과 "
            "pane-gated indent를 비교한다."
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

    print("=== exp 035: LLM pane gate -> pane별 indent tier ===")
    for result in results:
        if result.get("status") != "ok":
            print(f"- {result['id']}: {result.get('status')}")
            continue
        print(
            f"- {result['id']}: gt={result['ground_truth_panes']} "
            f"pred={result['predicted_panes']} conf={result['pane_confidence']} "
            f"route={result['route']} correct={result['is_pane_correct']}"
        )
        print(f"    baseline_indent={result['baseline_whole']['indent_distribution']}")
        print(f"    gated_indent   ={result['gated']['indent_distribution']}")
        if result["gated"].get("panes"):
            for pane, info in result["gated"]["panes"].items():
                print(f"      {pane}: cuts={info['indent_cuts']} dist={info['indent_distribution']}")
    print(summary["finding"])


if __name__ == "__main__":
    main()
