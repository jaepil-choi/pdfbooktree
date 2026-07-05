"""experiment 059: Document Parse의 output_formats(text/html/markdown)를 한 번에
같이 요청해서, 같은 page(Luenberger 42쪽 - table과 equation을 포함)에서 포맷별로
구조를 어떻게 다르게 표현하는지 비교한다.

배경: 057/058은 output_formats=["text"]만 요청했다. 사용자가 table/equation
표현 방식을 포맷별로 비교하고 싶어해서, 이번엔 한 번의 호출에
output_formats=["text","html","markdown"]를 모두 넣어 응답을 받는다(Document Parse는
한 번의 요청으로 여러 포맷을 동시에 반환한다 - 포맷마다 별도 호출이 필요 없다).

캐시: 057/058과 같은 page·같은 dpi(300)를 쓰지만 output_formats가 다르므로
sha1(png)만으로는 캐시가 겹치지 않는다(파일 바이트는 같아도 요청 파라미터가 다르면
다른 응답이 온다). 039의 관례대로 model+파라미터 태그를 캐시 키에 포함한다.

실행:
    uv run python experiments/059_document_parse_output_format_compare.py
출력:
    experiments/outputs/059_document_parse_output_format_compare/
        - full_text.txt       : content.text 전체
        - full_html.html      : content.html 전체
        - full_markdown.md    : content.markdown 전체
        - elements_compare.txt: element(문단/표/수식 등)마다 세 포맷 표현을 나란히 기록
        - cache/              : 원본 API 응답 캐시
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import requests
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "059_document_parse_output_format_compare"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
CACHE_DIR = OUTPUT_DIR / "cache"

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
DIGITIZE_URL = f"{UPSTAGE_BASE_URL}/document-digitization"
MODEL = "document-parse"
RENDER_DPI = 300

PDF_PATH = (
    ROOT_DIR
    / "data"
    / "scanned-pdf-indexed"
    / "David G. Luenberger, Investment Science 2nd - adobeOCR - indexed.pdf"
)
PAGE_1INDEXED = 42
OUTPUT_FORMATS = ["text", "html", "markdown"]


def render_png(pdf_path: Path, page_1indexed: int, dpi: int = RENDER_DPI) -> bytes:
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_1indexed - 1]
        return page.get_pixmap(dpi=dpi).tobytes("png")
    finally:
        doc.close()


def _api_key() -> str:
    key = os.environ.get("UPSTAGE_API_KEY")
    if not key:
        raise RuntimeError("UPSTAGE_API_KEY가 설정되지 않았다.")
    return key


def digitize(png: bytes, extra: dict[str, str]) -> dict[str, Any]:
    h = hashlib.sha1(png).hexdigest()[:16]
    tag = MODEL + "_" + "_".join(f"{k}{v}" for k, v in sorted(extra.items()))
    tag = re.sub(r"[^0-9A-Za-z._-]+", "", tag)[:80]
    cache = CACHE_DIR / f"{tag}_{h}.json"
    if cache.exists():
        print(f"[cache] 재사용: {cache.name}")
        return json.loads(cache.read_text(encoding="utf-8"))

    data = {"model": MODEL, **extra}
    delay = 6.0
    last_exc: Exception | None = None
    for attempt in range(7):
        resp = requests.post(
            DIGITIZE_URL,
            headers={"Authorization": f"Bearer {_api_key()}"},
            files={"document": ("page.png", io.BytesIO(png), "image/png")},
            data=data,
            timeout=180,
        )
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", delay))
            print(f"      429 rate-limited, {wait:.0f}s 대기 (attempt {attempt + 1})", flush=True)
            time.sleep(wait)
            delay = min(delay * 1.6, 60.0)
            continue
        try:
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(delay)
            delay = min(delay * 1.6, 60.0)
            continue
        out = resp.json()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        return out
    raise last_exc or RuntimeError("Upstage digitization 반복 429로 실패")


def format_elements_compare(resp: dict[str, Any]) -> str:
    out: list[str] = []
    for el in resp.get("elements", []):
        out.append(f"{'=' * 70}")
        out.append(f"[id={el.get('id')} category={el.get('category')}]")
        content = el.get("content", {})
        for fmt in OUTPUT_FORMATS:
            out.append(f"--- {fmt} ---")
            out.append(content.get(fmt, "") or "(empty)")
        out.append("")
    return "\n".join(out) + "\n"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[render] {PDF_PATH.name} {PAGE_1INDEXED}쪽을 {RENDER_DPI}dpi로 렌더링")
    png = render_png(PDF_PATH, PAGE_1INDEXED)

    extra = {
        "output_formats": json.dumps(OUTPUT_FORMATS),
        "coordinates": "true",
        "words": "true",
    }
    print(f"[document-parse] output_formats={OUTPUT_FORMATS} 호출 중...")
    t0 = time.time()
    resp = digitize(png, extra)
    elapsed = time.time() - t0
    print(f"[document-parse] 완료: {elapsed:.2f}s, elements={len(resp.get('elements', []))}")

    content = resp.get("content", {})
    (OUTPUT_DIR / "full_text.txt").write_text(content.get("text", ""), encoding="utf-8")
    (OUTPUT_DIR / "full_html.html").write_text(content.get("html", ""), encoding="utf-8")
    (OUTPUT_DIR / "full_markdown.md").write_text(content.get("markdown", ""), encoding="utf-8")
    (OUTPUT_DIR / "elements_compare.txt").write_text(
        format_elements_compare(resp), encoding="utf-8"
    )

    # table/equation 카테고리만 따로 뽑아 사람이 바로 볼 수 있게 요약도 남긴다.
    categories_present = sorted({el.get("category") for el in resp.get("elements", [])})
    table_els = [el for el in resp.get("elements", []) if el.get("category") == "table"]
    equation_els = [el for el in resp.get("elements", []) if el.get("category") == "equation"]

    print(f"[done] categories={categories_present} tables={len(table_els)} equations={len(equation_els)}")

    record_experiment(resp, elapsed, categories_present, len(table_els), len(equation_els))


def record_experiment(
    resp: dict[str, Any],
    elapsed: float,
    categories_present: list[str],
    n_tables: int,
    n_equations: int,
) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    table_el = next((el for el in resp.get("elements", []) if el.get("category") == "table"), None)
    equation_el = next(
        (el for el in resp.get("elements", []) if el.get("category") == "equation"), None
    )
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "Document Parse의 output_formats(text/html/markdown)를 한 번의 호출로 "
            "동시에 요청해서, 같은 page(Luenberger 42쪽, table 1개+equation 1개 포함)에서 "
            "포맷별 표현 차이를 비교한다. 특히 table의 병합 헤더 셀(colspan)이 포맷마다 "
            "보존되는지가 관심사였다."
        ),
        "inputs": [str(PDF_PATH.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "output_formats_requested": OUTPUT_FORMATS,
        "render_dpi": RENDER_DPI,
        "elapsed_sec": elapsed,
        "categories_present": categories_present,
        "n_tables": n_tables,
        "n_equations": n_equations,
        "finding": (
            "세 포맷 모두 같은 응답 안에 함께 들어있다(포맷마다 별도 호출 불필요). "
            "table: html만 실제 <table><thead><tbody> 구조와 colspan='8'로 병합 헤더 셀을 "
            "보존한다. text/markdown은 둘 다 GitHub 스타일 파이프 테이블로 평탄화되는데, "
            "병합된 헤더('Interest rate (%)')가 8개 열에 그대로 반복 복사되어 실제로는 "
            "1개 셀이 8개 열에 걸쳐있다는 정보가 사라진다(colspan 정보 유실). "
            "equation: text는 델리미터 없는 raw LaTeX을 주고("
            "'\\\\operatorname*{lim}_{m\\\\rightarrow\\\\infty}...'), html/markdown은 둘 다 "
            "동일하게 '$$...$$'로 감싼 LaTeX을 준다(html은 추가로 "
            "<p data-category='equation'>로 감싼다). "
            "결론: 표 구조(특히 병합 셀)를 온전히 보존해야 하면 html을, 사람이 읽기 "
            "좋은 평문/목차류 텍스트가 목적이면 text/markdown을 쓰는 게 맞다."
        ),
        "table_example": {
            "text": (table_el or {}).get("content", {}).get("text"),
            "html": (table_el or {}).get("content", {}).get("html"),
            "markdown": (table_el or {}).get("content", {}).get("markdown"),
        },
        "equation_example": {
            "text": (equation_el or {}).get("content", {}).get("text"),
            "html": (equation_el or {}).get("content", {}).get("html"),
            "markdown": (equation_el or {}).get("content", {}).get("markdown"),
        },
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["experiments"].append(entry)
    EXPERIMENTS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
