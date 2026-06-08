from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TypedDict

import fitz
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "004_llm_binomial_search_toc_pages"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
DEFAULT_MAX_TEXT_PAGES = 30
DEFAULT_MAX_PROMPT_CHARS = 14000

INPUT_PDFS = [
    {
        "id": "john_hull",
        "path": ROOT_DIR
        / "data"
        / "native-pdf-indexed"
        / "John Hull - Options, Futures, and Other Derivatives, Global Edition-Pearson (2021).pdf",
    },
    {
        "id": "shreve_binomial",
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-indexed"
        / "(Springer Finance) Steven E. Shreve - Stochastic Calculus for Finance I The Binomial Asset Pricing Model-Springer (2005)-indexed.pdf",
    },
    {
        "id": "luenberger_investment_science",
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-indexed"
        / "David G. Luenberger, Investment Science 2nd - adobeOCR - indexed.pdf",
    },
]

REVIEWED_TOC_PAGE_RANGES = {
    "john_hull": {
        "accepted_pages": list(range(5, 16)),
        "core_pages": list(range(6, 16)),
        "note": "page 5는 contents in brief라서 optional이고, 실질 TOC는 page 6-15다.",
    },
    "shreve_binomial": {
        "accepted_pages": list(range(3, 12)),
        "core_pages": list(range(3, 12)),
        "note": "page 3-11이 TOC다.",
    },
    "luenberger_investment_science": {
        "accepted_pages": list(range(7, 21)),
        "core_pages": list(range(9, 21)),
        "note": "page 7-8은 brief contents라서 optional이고, 실질 TOC는 page 9-20이다.",
    },
}


class PageSample(TypedDict):
    pdf_page: int
    text: str
    text_preview: str
    char_count: int


class TocProbeDecision(BaseModel):
    is_toc_page: bool = Field(
        description="현재 페이지가 목차 또는 목차의 일부이면 true다.",
    )
    direction: Literal["left", "right", "unknown"] = Field(
        description=(
            "목차 페이지가 아니면 다음 탐색 방향이다. 현재 페이지가 목차보다 뒤쪽 내용이면 "
            "left, 목차보다 앞쪽 내용이면 right, 판단 불가능하면 unknown이다."
        ),
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="판단 신뢰도다.",
    )
    rationale: str = Field(description="판단 근거를 한두 문장으로 설명한다.")


class TocBoundaryDecision(BaseModel):
    is_toc_page: bool = Field(
        description="현재 페이지가 연속된 목차 구간에 포함되면 true다.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="판단 신뢰도다.",
    )
    rationale: str = Field(description="판단 근거를 한두 문장으로 설명한다.")


class SearchState(TypedDict, total=False):
    pdf_id: str
    pages: dict[int, PageSample]
    max_pages: int
    max_prompt_chars: int
    low: int
    high: int
    probe_page: int | None
    found_page: int | None
    toc_pages: list[int]
    probe_decisions: list[dict[str, Any]]
    boundary_decisions: list[dict[str, Any]]
    left_cursor: int
    right_cursor: int
    left_done: bool
    right_done: bool
    result: dict[str, Any]


def normalize_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\x00", " ").splitlines()).strip()


def truncate_for_prompt(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head_chars = max_chars // 2
    tail_chars = max_chars - head_chars
    return (
        text[:head_chars]
        + "\n\n[...중간 텍스트 생략...]\n\n"
        + text[-tail_chars:]
    )


def extract_page_texts(pdf_path: Path, max_pages: int) -> dict[int, PageSample]:
    pages = {}
    with fitz.open(pdf_path) as document:
        for page_index in range(min(max_pages, document.page_count)):
            page_number = page_index + 1
            text = normalize_text(document.load_page(page_index).get_text("text"))
            pages[page_number] = {
                "pdf_page": page_number,
                "text": text,
                "text_preview": " ".join(text.split())[:700],
                "char_count": len(text),
            }
    return pages


def build_llm(model: str, temperature: float) -> ChatOpenAI:
    load_dotenv(ROOT_DIR / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY가 없습니다. 프로젝트 루트의 .env에 OPENAI_API_KEY를 넣은 뒤 다시 실행하세요."
        )
    return ChatOpenAI(model=model, temperature=temperature)


def build_probe_chain(llm: ChatOpenAI) -> Any:
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "너는 PDF 책의 앞부분에서 목차 페이지 범위를 찾는 분류기다. "
                    "주어진 페이지 텍스트만 보고 현재 페이지가 목차인지 판단한다. "
                    "목차는 첫 페이지에만 Contents 제목이 있을 수 있고, 뒤쪽 연속 페이지에는 제목 없이 "
                    "장/절/소절 제목과 페이지 번호 또는 OCR로 손상된 항목 목록만 이어질 수 있다. "
                    "Summary, Exercises, References 같은 단어도 장별 항목으로 반복되면 목차의 일부다. "
                    "반대로 Business Snapshots, Technical Notes, list of figures, list of tables, "
                    "색인, 참고문헌처럼 목차 뒤에 붙는 보조 목록은 main table of contents가 아니면 false다. "
                    "목차가 아니라면 현재 페이지가 목차 이전의 표지/헌사/서문/저자소개/앞부분인지, "
                    "또는 목차 이후의 본문/장 시작/본문 내용인지 판단해 다음 탐색 방향을 고른다. "
                    "left는 더 앞 페이지를 봐야 한다는 뜻이고, right는 더 뒤 페이지를 봐야 한다는 뜻이다. "
                    "예를 들어 현재 페이지가 CHAPTER 1 본문, 수식, 정의, 일반 본문이면 목차는 앞쪽에 있으므로 "
                    "반드시 direction='left'다. 현재 페이지가 표지, 저작권, 헌사, Preface 이전 내용이면 "
                    "목차는 뒤쪽에 있으므로 direction='right'다. "
                    "rationale에 쓴 방향과 direction 필드는 반드시 일치해야 한다. "
                    "가능한 한 unknown을 피하고 이진 탐색이 진행되도록 left 또는 right를 선택한다."
                ),
            ),
            (
                "human",
                (
                    "PDF id: {pdf_id}\n"
                    "관찰 범위: 1-{max_pages} 페이지\n"
                    "현재 이진 탐색 구간: {low}-{high}\n"
                    "판단할 페이지: {page_number}\n\n"
                    "[페이지 텍스트]\n{text}"
                ),
            ),
        ]
    )
    return prompt | llm.with_structured_output(TocProbeDecision)


def build_boundary_chain(llm: ChatOpenAI) -> Any:
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "너는 이미 발견된 목차 페이지 주변에서 연속된 목차 구간의 경계를 찾는 분류기다. "
                    "현재 페이지가 목차, contents in brief, table of contents, 또는 그 연속 페이지라면 true다. "
                    "연속 목차 페이지는 Contents 제목이 없어도 장/절/소절 제목이 빽빽하게 나열되고, "
                    "페이지 번호가 있거나 OCR 손상 때문에 일부 번호가 사라진 형태일 수 있다. "
                    "Summary, Exercises, References 같은 항목도 장별 목차 항목으로 반복되면 true다. "
                    "본문 장 시작은 문단 설명, 수식, 긴 문장, 본문형 서술이 많으면 false다. "
                    "Business Snapshots, Technical Notes, list of figures, list of tables, 색인, "
                    "참고문헌처럼 main table of contents 뒤에 붙는 보조 목록은 false다."
                ),
            ),
            (
                "human",
                (
                    "PDF id: {pdf_id}\n"
                    "발견된 목차 기준 페이지: {found_page}\n"
                    "확장 방향: {direction}\n"
                    "판단할 페이지: {page_number}\n\n"
                    "[페이지 텍스트]\n{text}"
                ),
            ),
        ]
    )
    return prompt | llm.with_structured_output(TocBoundaryDecision)


def classify_probe_page(
    chain: Any,
    state: SearchState,
    page_number: int,
) -> dict[str, Any]:
    page = state["pages"][page_number]
    decision = chain.invoke(
        {
            "pdf_id": state["pdf_id"],
            "max_pages": state["max_pages"],
            "low": state["low"],
            "high": state["high"],
            "page_number": page_number,
            "text": truncate_for_prompt(page["text"], state["max_prompt_chars"]),
        }
    )
    return decision.model_dump() | {
        "pdf_page": page_number,
        "low": state["low"],
        "high": state["high"],
        "text_preview": page["text_preview"],
    }


def classify_boundary_page(
    chain: Any,
    state: SearchState,
    page_number: int,
    direction: Literal["left", "right"],
) -> dict[str, Any]:
    page = state["pages"][page_number]
    decision = chain.invoke(
        {
            "pdf_id": state["pdf_id"],
            "found_page": state["found_page"],
            "direction": direction,
            "page_number": page_number,
            "text": truncate_for_prompt(page["text"], state["max_prompt_chars"]),
        }
    )
    return decision.model_dump() | {
        "pdf_page": page_number,
        "direction": direction,
        "text_preview": page["text_preview"],
    }


def initialize_search(state: SearchState) -> SearchState:
    page_numbers = sorted(state["pages"])
    low = page_numbers[0]
    high = page_numbers[-1]
    return {
        "low": low,
        "high": high,
        "probe_page": (low + high) // 2,
        "found_page": None,
        "toc_pages": [],
        "probe_decisions": [],
        "boundary_decisions": [],
        "left_done": False,
        "right_done": False,
    }


def make_probe_midpoint_node(chain: Any) -> Any:
    def probe_midpoint(state: SearchState) -> SearchState:
        probe_page = state["probe_page"]
        if probe_page is None:
            return {}

        decision = classify_probe_page(chain, state, probe_page)
        probe_decisions = state["probe_decisions"] + [decision]

        if decision["is_toc_page"]:
            return {
                "found_page": probe_page,
                "toc_pages": sorted(set(state["toc_pages"] + [probe_page])),
                "probe_decisions": probe_decisions,
                "left_cursor": probe_page - 1,
                "right_cursor": probe_page + 1,
                "left_done": probe_page <= 1,
                "right_done": probe_page >= state["max_pages"],
            }

        low = state["low"]
        high = state["high"]
        if decision["direction"] == "left":
            high = probe_page - 1
        elif decision["direction"] == "right":
            low = probe_page + 1
        else:
            low = high + 1

        next_probe = (low + high) // 2 if low <= high else None
        return {
            "low": low,
            "high": high,
            "probe_page": next_probe,
            "probe_decisions": probe_decisions,
        }

    return probe_midpoint


def make_expand_left_node(chain: Any) -> Any:
    def expand_left(state: SearchState) -> SearchState:
        cursor = state["left_cursor"]
        if cursor < 1 or cursor not in state["pages"]:
            return {"left_done": True}

        decision = classify_boundary_page(chain, state, cursor, "left")
        boundary_decisions = state["boundary_decisions"] + [decision]
        if decision["is_toc_page"]:
            return {
                "toc_pages": sorted(set(state["toc_pages"] + [cursor])),
                "left_cursor": cursor - 1,
                "boundary_decisions": boundary_decisions,
            }
        return {
            "left_done": True,
            "boundary_decisions": boundary_decisions,
        }

    return expand_left


def make_expand_right_node(chain: Any) -> Any:
    def expand_right(state: SearchState) -> SearchState:
        cursor = state["right_cursor"]
        if cursor > state["max_pages"] or cursor not in state["pages"]:
            return {"right_done": True}

        decision = classify_boundary_page(chain, state, cursor, "right")
        boundary_decisions = state["boundary_decisions"] + [decision]
        if decision["is_toc_page"]:
            return {
                "toc_pages": sorted(set(state["toc_pages"] + [cursor])),
                "right_cursor": cursor + 1,
                "boundary_decisions": boundary_decisions,
            }
        return {
            "right_done": True,
            "boundary_decisions": boundary_decisions,
        }

    return expand_right


def finish_search(state: SearchState) -> SearchState:
    toc_pages = sorted(state["toc_pages"])
    if toc_pages:
        result = {
            "found": True,
            "toc_pages": toc_pages,
            "toc_range": {
                "start": toc_pages[0],
                "end": toc_pages[-1],
                "length": len(toc_pages),
            },
            "probe_count": len(state["probe_decisions"]),
            "boundary_probe_count": len(state["boundary_decisions"]),
        }
    else:
        result = {
            "found": False,
            "toc_pages": [],
            "toc_range": None,
            "probe_count": len(state["probe_decisions"]),
            "boundary_probe_count": len(state["boundary_decisions"]),
        }
    return {"result": result}


def route_after_probe(state: SearchState) -> str:
    if state.get("found_page") is not None:
        return "expand_left"
    if state.get("probe_page") is not None:
        return "probe_midpoint"
    return "finish"


def route_after_left(state: SearchState) -> str:
    if not state["left_done"]:
        return "expand_left"
    return "expand_right"


def route_after_right(state: SearchState) -> str:
    if not state["right_done"]:
        return "expand_right"
    return "finish"


def build_search_graph(llm: ChatOpenAI) -> Any:
    probe_chain = build_probe_chain(llm)
    boundary_chain = build_boundary_chain(llm)

    graph = StateGraph(SearchState)
    graph.add_node("initialize_search", initialize_search)
    graph.add_node("probe_midpoint", make_probe_midpoint_node(probe_chain))
    graph.add_node("expand_left", make_expand_left_node(boundary_chain))
    graph.add_node("expand_right", make_expand_right_node(boundary_chain))
    graph.add_node("finish", finish_search)

    graph.set_entry_point("initialize_search")
    graph.add_edge("initialize_search", "probe_midpoint")
    graph.add_conditional_edges(
        "probe_midpoint",
        route_after_probe,
        {
            "probe_midpoint": "probe_midpoint",
            "expand_left": "expand_left",
            "finish": "finish",
        },
    )
    graph.add_conditional_edges(
        "expand_left",
        route_after_left,
        {
            "expand_left": "expand_left",
            "expand_right": "expand_right",
        },
    )
    graph.add_conditional_edges(
        "expand_right",
        route_after_right,
        {
            "expand_right": "expand_right",
            "finish": "finish",
        },
    )
    graph.add_edge("finish", END)
    return graph.compile()


def analyze_pdf(
    graph: Any,
    pdf_id: str,
    pdf_path: Path,
    model: str,
    temperature: float,
    max_pages: int,
    max_prompt_chars: int,
) -> dict[str, Any]:
    output_dir = OUTPUT_DIR / pdf_id
    output_dir.mkdir(parents=True, exist_ok=True)

    pages = extract_page_texts(pdf_path, max_pages)
    final_state = graph.invoke(
        {
            "pdf_id": pdf_id,
            "pages": pages,
            "max_pages": len(pages),
            "max_prompt_chars": max_prompt_chars,
        },
        {"recursion_limit": 80},
    )
    comparison = compare_with_reviewed_range(
        predicted_pages=final_state["result"]["toc_pages"],
        reviewed_range=REVIEWED_TOC_PAGE_RANGES.get(pdf_id),
    )

    write_jsonl(output_dir / "page_texts_first_30.jsonl", list(pages.values()))
    write_jsonl(output_dir / "probe_decisions.jsonl", final_state["probe_decisions"])
    write_jsonl(output_dir / "boundary_decisions.jsonl", final_state["boundary_decisions"])
    run_config = {
        "model": model,
        "temperature": temperature,
        "max_pages": max_pages,
        "max_prompt_chars": max_prompt_chars,
    }
    write_json(
        output_dir / "result.json",
        final_state["result"] | {"comparison": comparison, "run_config": run_config},
    )
    (output_dir / "report.md").write_text(
        build_report(pdf_id, pdf_path, final_state, comparison, run_config),
        encoding="utf-8",
    )

    return {
        "pdf_id": pdf_id,
        "input_pdf": str(pdf_path.relative_to(ROOT_DIR)),
        "run_config": run_config,
        "result": final_state["result"],
        "probe_decisions": final_state["probe_decisions"],
        "boundary_decisions": final_state["boundary_decisions"],
        "reviewed_toc_page_comparison": comparison,
    }


def compare_with_reviewed_range(
    predicted_pages: list[int],
    reviewed_range: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if reviewed_range is None:
        return None

    predicted = set(predicted_pages)
    accepted = set(reviewed_range["accepted_pages"])
    core = set(reviewed_range["core_pages"])
    return {
        "note": reviewed_range["note"],
        "predicted_pages": sorted(predicted),
        "accepted_pages": sorted(accepted),
        "core_pages": sorted(core),
        "accepted_comparison": compare_page_sets(predicted, accepted),
        "core_comparison": compare_page_sets(predicted, core),
    }


def compare_page_sets(predicted: set[int], expected: set[int]) -> dict[str, Any]:
    true_positive = predicted & expected
    missing = expected - predicted
    extra = predicted - expected
    precision = len(true_positive) / len(predicted) if predicted else None
    recall = len(true_positive) / len(expected) if expected else None
    return {
        "true_positive_pages": sorted(true_positive),
        "missing_pages": sorted(missing),
        "extra_pages": sorted(extra),
        "precision": precision,
        "recall": recall,
    }


def build_report(
    pdf_id: str,
    pdf_path: Path,
    final_state: SearchState,
    comparison: dict[str, Any] | None,
    run_config: dict[str, Any],
) -> str:
    result = final_state["result"]
    probe_lines = "\n".join(
        format_decision_line(decision) for decision in final_state["probe_decisions"]
    )
    boundary_lines = "\n".join(
        format_decision_line(decision) for decision in final_state["boundary_decisions"]
    )

    comparison_text = "검수 range가 없는 PDF라 비교하지 않았다."
    if comparison is not None:
        accepted = comparison["accepted_comparison"]
        comparison_text = (
            f"- 검수 메모: {comparison['note']}\n"
            f"- accepted expected: {comparison['accepted_pages']}\n"
            f"- accepted missing: {accepted['missing_pages']}\n"
            f"- accepted extra: {accepted['extra_pages']}\n"
            f"- accepted precision: {accepted['precision']}\n"
            f"- accepted recall: {accepted['recall']}"
        )

    return f"""# {pdf_id} LLM binomial search TOC pages

## 입력

- PDF: `{pdf_path.relative_to(ROOT_DIR)}`
- 관찰 범위: 첫 {final_state["max_pages"]}페이지
- 모델: `{run_config["model"]}`
- temperature: {run_config["temperature"]}

## 결과

- TOC 발견 여부: {result["found"]}
- 예측 TOC pages: {result["toc_pages"]}
- 예측 TOC range: {result["toc_range"]}
- 이진 탐색 probe 수: {result["probe_count"]}
- 경계 확장 probe 수: {result["boundary_probe_count"]}

## 이진 탐색 판단

{probe_lines}

## 경계 확장 판단

{boundary_lines}

## 사용자 검수 range 비교

{comparison_text}
"""


def format_decision_line(decision: dict[str, Any]) -> str:
    direction = decision.get("direction", "-")
    return (
        f"- page {decision['pdf_page']}: is_toc={decision['is_toc_page']}, "
        f"direction={direction}, confidence={decision['confidence']}, "
        f"reason={decision['rationale']}"
    )


def load_experiment_registry() -> dict[str, Any]:
    if not EXPERIMENTS_JSON.exists():
        return {"experiments": []}
    text = EXPERIMENTS_JSON.read_text(encoding="utf-8").strip()
    if not text:
        return {"experiments": []}
    loaded = json.loads(text)
    if isinstance(loaded, list):
        return {"experiments": loaded}
    if "experiments" not in loaded:
        loaded["experiments"] = []
    return loaded


def build_finding(results: list[dict[str, Any]]) -> str:
    parts = []
    for result in results:
        prediction = result["result"]
        comparison = result["reviewed_toc_page_comparison"]
        if comparison is None:
            parts.append(
                f"{result['pdf_id']}는 LLM binomial search로 {prediction['toc_pages']}를 예측했다."
            )
            continue

        accepted = comparison["accepted_comparison"]
        parts.append(
            f"{result['pdf_id']}는 LLM binomial search로 {prediction['toc_pages']}를 예측했고, "
            f"사용자 검수 accepted range 대비 precision {accepted['precision']}, "
            f"recall {accepted['recall']}, missing {accepted['missing_pages']}, "
            f"extra {accepted['extra_pages']}이다."
        )
    return " ".join(parts)


def update_experiment_registry(results: list[dict[str, Any]]) -> None:
    registry = load_experiment_registry()
    experiments = [
        experiment
        for experiment in registry["experiments"]
        if experiment.get("id") != EXPERIMENT_ID
    ]
    experiments.append(
        {
            "id": EXPERIMENT_ID,
            "purpose": (
                "첫 30페이지 텍스트를 대상으로 LLM이 현재 page가 목차인지, 아니면 목차를 찾기 위해 "
                "왼쪽/오른쪽 중 어디로 이동해야 하는지 판단하게 하고, LangGraph 상태 머신으로 "
                "binomial search와 greedy boundary expansion을 결합한다."
            ),
            "inputs": [result["input_pdf"] for result in results],
            "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
            "model": results[0]["run_config"]["model"] if results else None,
            "temperature": results[0]["run_config"]["temperature"] if results else None,
            "finding": build_finding(results),
            "ran_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    registry["experiments"] = experiments
    write_json(EXPERIMENTS_JSON, registry)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(text + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LLM과 LangGraph로 첫 30페이지 안의 TOC page range를 찾는 실험이다.",
    )
    parser.add_argument(
        "--pdf-id",
        default="all",
        choices=["all", *[item["id"] for item in INPUT_PDFS]],
        help="분석할 PDF id다.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
        help="LangChain ChatOpenAI에 넘길 모델명이다.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="LLM temperature다.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_TEXT_PAGES,
        help="앞에서 몇 페이지까지 관찰할지 정한다.",
    )
    parser.add_argument(
        "--max-prompt-chars",
        type=int,
        default=DEFAULT_MAX_PROMPT_CHARS,
        help="한 페이지 텍스트를 프롬프트에 넣을 때의 최대 문자 수다.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="결과 파일만 쓰고 콘솔 JSON 출력은 생략한다.",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    selected = [
        item
        for item in INPUT_PDFS
        if args.pdf_id == "all" or item["id"] == args.pdf_id
    ]
    if not selected:
        raise ValueError(f"분석할 PDF가 없습니다: {args.pdf_id}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    llm = build_llm(args.model, args.temperature)
    graph = build_search_graph(llm)
    results = []
    for item in selected:
        if not item["path"].exists():
            raise FileNotFoundError(item["path"])
        results.append(
            analyze_pdf(
                graph=graph,
                pdf_id=item["id"],
                pdf_path=item["path"],
                model=args.model,
                temperature=args.temperature,
                max_pages=args.max_pages,
                max_prompt_chars=args.max_prompt_chars,
            )
        )

    write_json(OUTPUT_DIR / "summary.json", results)
    update_experiment_registry(results)
    if not args.quiet:
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
