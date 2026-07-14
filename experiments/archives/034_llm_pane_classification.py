"""experiment 034: height tier만 주고 LLM이 1단/2단 목차를 판정한다.

목적:
- 032/033에서 Zvi Bodie 목차는 2단 pane, 퀀트의 세계 목차는 1단 pane으로 보였다.
- 이번 실험은 LLM에게 줄 텍스트와 height tier만 보내고, x bin/좌표/indent 신호 없이
  문서가 1 pane인지 2 pane인지 판단하게 한다.
- 2단 목차는 y-KDE로 같은 y row를 합치면 한 줄에 서로 독립적인 목차 항목이 섞이는
  패턴이 자주 나오므로, LLM이 이 텍스트 패턴과 height tier만으로 판정 가능한지 본다.

실행:
    uv run python experiments/034_llm_pane_classification.py
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
EXPERIMENT_ID = "034_llm_pane_classification"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
LABELS_JSON = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
MODEL = "solar-pro3"

TARGET_IDS = ["zvi_bodie_investments", "quant_world"]
GROUND_TRUTH_PANES = {
    "zvi_bodie_investments": 2,
    "quant_world": 1,
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
# 텍스트와 line 재구성
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


def extract_textboxes(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """TOC page의 span/textbox를 추출한다. LLM payload에는 좌표를 보내지 않는다."""

    boxes: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for pdf_page in toc_pages:
            if pdf_page < 1 or pdf_page > document.page_count:
                continue
            page = document.load_page(pdf_page - 1)
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


def reconstruct_lines_from_y_kde(boxes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """page 전체 y-KDE로 같은 row의 span을 이어 붙인다."""

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
    for box in boxes:
        box["y_tier"] = band_low_first(box["y0"], y_cuts)

    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for box in boxes:
        if not box["is_content"] and not _DIGIT.search(box["text"]):
            continue
        key = (int(box["pdf_page"]), int(box["y_tier"]))
        grouped.setdefault(key, []).append(box)

    lines: list[dict[str, Any]] = []
    for (pdf_page, y_tier), members in sorted(grouped.items()):
        ordered = sorted(members, key=lambda value: (value["x0"], value["span_index"]))
        content_members = [member for member in ordered if member["is_content"]]
        if not content_members:
            continue
        text = normalize_text(" ".join(member["text"] for member in ordered))
        content_text = normalize_text(" ".join(member["text"] for member in content_members))
        lines.append(
            {
                "pdf_page": pdf_page,
                "y_tier": y_tier,
                "text": text,
                "content_text": content_text,
                "height": round(max(member["span_height"] for member in content_members), 2),
                "box_count": len(ordered),
                "content_box_count": len(content_members),
            }
        )

    height_cuts = cluster_cut_points(
        [line["height"] for line in lines if not is_title_word(line["content_text"])],
        grid_size=2048,
    )
    for line_no, line in enumerate(lines, start=1):
        line["line_no"] = line_no
        line["height_tier"] = height_tier(line["height"], height_cuts)

    debug = {
        "box_count": len(boxes),
        "content_box_count": len(content_boxes),
        "line_count": len(lines),
        "y_bandwidth": round(y_bandwidth, 3),
        "y_cut_count": len(y_cuts),
        "height_cuts": [round(value, 2) for value in height_cuts],
        "height_tier_distribution": {
            str(tier): count
            for tier, count in sorted(Counter(line["height_tier"] for line in lines).items())
        },
    }
    return lines, debug


# ---------------------------------------------------------------------------
# LLM 호출
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


def build_llm_payload(target: dict[str, Any], lines: list[dict[str, Any]], debug: dict[str, Any]) -> dict[str, Any]:
    """좌표와 x bin 없이 LLM에 보낼 payload를 만든다."""

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
    """수동 정답 라벨 파일에서 이번 대상 2권을 읽는다."""

    labels = json.loads(LABELS_JSON.read_text(encoding="utf-8"))["labels"]
    by_id = {label["id"]: label for label in labels}
    missing = [target_id for target_id in TARGET_IDS if target_id not in by_id]
    if missing:
        raise RuntimeError(f"라벨 파일에 대상 id가 없다: {missing}")
    return [by_id[target_id] for target_id in TARGET_IDS]


def run_one(target: dict[str, Any]) -> dict[str, Any]:
    """한 권에 대해 line 재구성, payload 저장, LLM 판정을 수행한다."""

    pdf_path = ROOT_DIR / target["input_pdf"]
    result: dict[str, Any] = {
        "id": target["id"],
        "input_pdf": target["input_pdf"],
        "toc_pages": target["toc_pages"],
        "ground_truth_panes": GROUND_TRUTH_PANES[target["id"]],
    }
    if not pdf_path.exists():
        result["status"] = "missing_pdf"
        return result

    boxes = extract_textboxes(pdf_path, target["toc_pages"])
    lines, debug = reconstruct_lines_from_y_kde(boxes)
    payload = build_llm_payload(target, lines, debug)
    llm = classify_panes(payload)
    predicted = int(llm.get("pane_count", 0) or 0)

    target_dir = OUTPUT_DIR / target["id"]
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "lines_height_tier_only.json").write_text(
        json.dumps(lines, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (target_dir / "llm_payload_height_tier_only.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (target_dir / "llm_response.json").write_text(
        json.dumps(llm, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result.update(
        {
            "status": "ok",
            "line_count": len(lines),
            "debug": debug,
            "llm": llm,
            "predicted_panes": predicted,
            "is_correct": predicted == GROUND_TRUTH_PANES[target["id"]],
            "outputs": {
                "lines": str((target_dir / "lines_height_tier_only.json").relative_to(ROOT_DIR)),
                "payload": str((target_dir / "llm_payload_height_tier_only.json").relative_to(ROOT_DIR)),
                "response": str((target_dir / "llm_response.json").relative_to(ROOT_DIR)),
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
        total += 1
        if result["is_correct"]:
            correct += 1
        llm = result["llm"]
        parts.append(
            f"{result['id']}: gt={result['ground_truth_panes']}pane, "
            f"LLM={result['predicted_panes']}pane, "
            f"confidence={llm.get('confidence')}, lines={result['line_count']}, "
            f"height_tiers={result['debug']['height_tier_distribution']}, "
            f"evidence={llm.get('evidence_line_numbers')}"
        )
    return (
        "height_tier만 포함하고 x bin/좌표/indent를 제외한 payload로 1-pane/2-pane을 판정했다. "
        + " | ".join(parts)
        + f" || accuracy={correct}/{total}. "
        "Zvi와 퀀트의 세계 비교에서 LLM이 텍스트 row 병합 패턴만으로 pane 수를 구분할 수 있는지 확인했다."
    )


def record_experiment(summary: dict[str, Any]) -> None:
    """실험 registry에 이번 결과를 기록한다."""

    registry = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "Zvi Bodie Investments와 퀀트의 세계 TOC page를 대상으로, LLM에게 line text와 "
            "height tier만 보내고 x bin/좌표/indent 없이 2 pane 문서인지 1 pane 문서인지 "
            "판정하게 한다. 2단 목차는 y-KDE row 재구성 시 독립 항목이 한 줄에 병합되는 "
            "패턴이 생기는지, LLM이 그 텍스트 패턴을 읽는지 비교한다."
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

    print("=== exp 034: LLM pane classification with height tier only ===")
    for result in results:
        if result.get("status") != "ok":
            print(f"- {result['id']}: {result.get('status')}")
            continue
        print(
            f"- {result['id']}: gt={result['ground_truth_panes']} "
            f"pred={result['predicted_panes']} "
            f"confidence={result['llm'].get('confidence')} "
            f"correct={result['is_correct']}"
        )
        print(f"  reason={result['llm'].get('reason')}")
    print(summary["finding"])


if __name__ == "__main__":
    main()

