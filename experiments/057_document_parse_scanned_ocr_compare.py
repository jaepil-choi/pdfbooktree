"""experiment 057: 056(PaddleOCR/EasyOCR)과 같은 page 셋에 Upstage Document Parse를
추가로 돌려 3-way 비교가 되게 한다.

배경: 사용자가 애초에 요청한 비교는 "document parse api와 paddleocr, easyocr"
3자 비교였는데, 056에서는 로컬 OCR 두 개만 돌렸다. 이 실험은 056과 정확히 같은
책·같은 page(TOC 전체 range + 책마다 42쪽 샘플)에 Upstage document-digitization의
model=document-parse를 호출해서 결과를 txt로 남긴다. 정확도 판정은 여기서도
하지 않는다(사람이 눈으로 확인).

Document Parse 호출 규약(039/040에서 확립됨, memory에는 없던 부분이라 여기 docstring에도
남긴다):
    - endpoint: POST https://api.upstage.ai/v1/document-digitization
    - model=document-parse (model=ocr는 과금되므로 이 저장소에서 사용 금지)
    - output_formats=["text"], coordinates=true, words=true
    - free tier RPS 제한으로 429가 잦아서 지수 backoff 재시도 + 성공 후 짧은 throttle 필요
    - 응답의 content.text가 이미 사람이 읽기 좋은 순서로 재구성된 페이지 전체 텍스트다.
      elements[]는 category(heading/index/footer 등)가 붙은 구조 단위이고, 각 element
      안에 words[]가 word 단위 좌표+confidence로 들어있다.

056과 동일하게 디스크 캐시(page png의 sha1 해시 키)를 써서 재실행 시 과금 재호출을
막는다.

실행:
    uv run python experiments/057_document_parse_scanned_ocr_compare.py
출력:
    experiments/outputs/057_document_parse_scanned_ocr_compare/
        - <book_id>/toc_p<NNN>_documentparse.txt   : Document Parse 인식 결과
        - <book_id>/sample_p042_documentparse.txt  : Document Parse 인식 결과
        - cache/                                   : Upstage 응답 원본 캐시(JSON)
        - timing_summary.json                      : page별 소요 시간, usage(과금 페이지 수)
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
EXPERIMENT_ID = "057_document_parse_scanned_ocr_compare"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
CACHE_DIR = OUTPUT_DIR / "cache"

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
DIGITIZE_URL = f"{UPSTAGE_BASE_URL}/document-digitization"
MODEL = "document-parse"
RENDER_DPI = 300
SAMPLE_PAGE_1INDEXED = 42

# 056과 동일한 책/페이지 정의(같은 page를 3-way로 비교하기 위해 그대로 맞춘다).
BOOKS: dict[str, dict[str, Any]] = {
    "shreve_binomial": {
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-indexed"
        / "(Springer Finance) Steven E. Shreve - Stochastic Calculus for Finance I The Binomial Asset Pricing Model-Springer (2005)-indexed.pdf",
        "toc_pages": list(range(3, 12)),
    },
    "luenberger_investment_science": {
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-indexed"
        / "David G. Luenberger, Investment Science 2nd - adobeOCR - indexed.pdf",
        "toc_pages": list(range(7, 21)),
    },
    "algorithm_nine": {
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-not-indexed"
        / "미래를_바꾼_아홉가지_알고리즘_-_존_맥코믹-compressed[algorithm cs book].pdf",
        "toc_pages": [12],
    },
    "algorithms_to_live_by": {
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-not-indexed"
        / "알고리즘_인생을계산하다_The_computer_science_of_human_decisions_-_BrianChristian.pdf",
        "toc_pages": list(range(16, 20)),
    },
    "suri_tonggyehak": {
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-not-indexed"
        / "수리통계학(개정판)-김우철_upocr_merged.pdf",
        "toc_pages": list(range(4, 8)),
    },
}


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


def digitize(png: bytes) -> dict[str, Any]:
    """model=document-parse 호출. png의 sha1 해시로 디스크 캐시해서 재호출/과금을 막는다."""
    h = hashlib.sha1(png).hexdigest()[:16]
    cache = CACHE_DIR / f"{MODEL}_{h}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    data = {
        "model": MODEL,
        "output_formats": '["text"]',
        "coordinates": "true",
        "words": "true",
    }
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
        time.sleep(1.2)
        return out
    raise last_exc or RuntimeError("Upstage digitization 반복 429로 실패")


def format_result_txt(resp: dict[str, Any], elapsed: float) -> str:
    elements = resp.get("elements", [])
    out: list[str] = []
    out.append(
        f"# engine=document-parse elapsed_sec={elapsed:.2f} elements={len(elements)} "
        f"usage={json.dumps(resp.get('usage', {}), ensure_ascii=False)}"
    )
    out.append("")
    out.append("## content.text (Document Parse가 재구성한 페이지 전체 텍스트)")
    out.append(resp.get("content", {}).get("text", ""))
    out.append("")
    out.append("## element 단위 detail(category + text + 평균 word confidence)")
    for el in elements:
        words = el.get("words") or []
        confs = [float(w.get("confidence", 1.0)) for w in words]
        avg_conf = sum(confs) / len(confs) if confs else float("nan")
        text = el.get("content", {}).get("text", "")
        out.append(f"[category={el.get('category')} avg_word_conf={avg_conf:.4f} words={len(words)}]")
        out.append(text)
        out.append("")
    return "\n".join(out) + "\n"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    timing: dict[str, Any] = {"render_dpi": RENDER_DPI, "pages": []}
    run_started = time.time()

    for book_id, meta in BOOKS.items():
        pdf_path: Path = meta["path"]
        toc_pages: list[int] = meta["toc_pages"]
        book_dir = OUTPUT_DIR / book_id
        book_dir.mkdir(parents=True, exist_ok=True)

        targets: list[tuple[str, int]] = [("toc", p) for p in toc_pages]
        targets.append(("sample", SAMPLE_PAGE_1INDEXED))

        for kind, page_no in targets:
            tag = f"{kind}_p{page_no:03d}"
            print(f"[document-parse] {book_id} {tag} 호출 중...")
            png = render_png(pdf_path, page_no)

            t0 = time.time()
            resp = digitize(png)
            elapsed = time.time() - t0

            (book_dir / f"{tag}_documentparse.txt").write_text(
                format_result_txt(resp, elapsed), encoding="utf-8"
            )
            print(
                f"[document-parse] {book_id} {tag} 완료: {elapsed:.2f}s, "
                f"elements={len(resp.get('elements', []))}"
            )

            timing["pages"].append(
                {
                    "book_id": book_id,
                    "kind": kind,
                    "page_1indexed": page_no,
                    "documentparse_sec": elapsed,
                    "documentparse_elements": len(resp.get("elements", [])),
                    "usage": resp.get("usage", {}),
                }
            )

    total_elapsed = time.time() - run_started
    timing["total_loop_sec"] = total_elapsed
    timing["total_pages"] = len(timing["pages"])
    timing["total_documentparse_sec"] = sum(p["documentparse_sec"] for p in timing["pages"])

    (OUTPUT_DIR / "timing_summary.json").write_text(
        json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"[done] pages={timing['total_pages']} "
        f"documentparse_total={timing['total_documentparse_sec']:.1f}s "
        f"loop_total={total_elapsed:.1f}s"
    )

    record_experiment(timing)


def record_experiment(timing: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "056(PaddleOCR/EasyOCR)과 정확히 같은 책·같은 page(TOC range 전체 + 책마다 "
            "42쪽 샘플)에 Upstage Document Parse(model=document-parse)를 호출해서 3-way "
            "OCR 비교가 되도록 한다. 정확도 판정은 사람이 결과 txt를 보고 직접 내린다."
        ),
        "inputs": [str(meta["path"].relative_to(ROOT_DIR)) for meta in BOOKS.values()],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "compare_with": "056_paddleocr_easyocr_scanned_ocr_compare",
        "toc_page_ranges": {
            book_id: {"toc_pages": meta["toc_pages"], "sample_page": SAMPLE_PAGE_1INDEXED}
            for book_id, meta in BOOKS.items()
        },
        "render_dpi": RENDER_DPI,
        "model": MODEL,
        "digitize_params": {"output_formats": ["text"], "coordinates": True, "words": True},
        "timing_summary": {
            "total_pages": timing["total_pages"],
            "total_documentparse_sec": timing["total_documentparse_sec"],
            "avg_documentparse_sec_per_page": timing["total_documentparse_sec"] / timing["total_pages"],
        },
        "finding": (
            "PENDING: 소요 시간만 자동 기록했고, 인식 품질은 사람이 outputs/의 txt를 "
            "056의 paddleocr/easyocr 결과와 직접 눈으로 비교해서 판단해야 한다."
        ),
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["experiments"].append(entry)
    EXPERIMENTS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
