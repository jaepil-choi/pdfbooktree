"""experiment 058: Luenberger 42쪽 하나를 뽑아서 Document Parse로 얻은 텍스트를
image 위에 invisible text layer로 overlay한 PDF를 만든다(ocrmypdf 스타일 sandwich PDF).
표/수식까지 정보 손실 없이 들어가도록 element 단위로 임베딩 전략을 나눈다.

배경: 057에서 Document Parse가 로컬 OCR(PaddleOCR/EasyOCR)보다 훨씬 빠르고 품질도
좋아 보였다. 이 실험은 "실제로 검색/선택 가능한 PDF를 만들 수 있는가"를 검증한다.
ocrmypdf 17.8.0(uv pip install로 설치, 공식 문서 권장 방식이라 pyproject.toml에는
uv add로 등록하지 않는다)의 소스를 참고했다: ocrmypdf는 hOCR/OCR 결과를 OcrElement
트리로 파싱한 뒤 fpdf_renderer.Fpdf2PdfRenderer로 invisible text(Tr 3)를 그리고 그
위에 원본 이미지를 얹는 "sandwich PDF"를 만든다(ocrmypdf/fpdf_renderer/renderer.py).
이 실험은 그 렌더러를 그대로 재사용한다(직접 재구현하지 않는다) — baseline slope,
회전, RTL, 글리프 커버리지 기반 폰트 선택 같은 까다로운 부분을 이미 잘 처리해주기
때문이다. 우리가 새로 만드는 부분은 Document Parse 응답을 ocrmypdf의 OcrElement
트리(page -> line -> word)로 변환하는 어댑터뿐이다.

[재작업 이유] 최초 버전은 모든 element의 word를 페이지 전체 기준으로 y-center
그리디 그룹핑해서 word 단위로만 심었다. 060에서 이 방식의 손실을 확인했다:
- equation: element.words[]가 이미 OCR/레이아웃 낱말 단위라 LaTeX 구조(위첨자,
  아래첨자, \\equiv)가 깨진 채로 들어있었다('lim [1+(r/m)]m = er / m→oo'). Document
  Parse의 content.text는 깨끗한 LaTeX('\\operatorname*{lim}_{m\\rightarrow\\infty}
  [1+(r/m)]^{m}\\equiv e^{r}')을 이미 주는데 그걸 안 쓰고 있었다.
- table: word들을 이었을 때 행/열 구분자가 전혀 없어서(파이프조차 없음) 표였다는
  사실 자체가 사라졌다. content.text/markdown은 최소한 파이프 테이블 구조는 준다.

[수정한 임베딩 전략] element마다 "word를 그냥 이어붙인 텍스트"와 "content.text"가
공백 정규화 후 일치하는지 먼저 확인한다.
    (a) 일치하면(문단/제목/머리말/꼬리말 등 대부분) — 기존처럼 word 단위로 심는다.
        위치 정밀도가 필요 이상으로 좋고, 어차피 손실이 없다는 게 실측으로 확인됐다.
    (b) 불일치하면(표, 수식처럼 word 나열만으로는 구조가 사라지는 element) —
        그 element 자신의 word만 다시 y-center로 줄(행) 단위로 묶고, content.text를
        줄바꿈으로 나눠(표의 "| --- |" 구분줄은 제거) 행 개수가 서로 맞으면 각 행의
        bbox에 그 행의 content.text 원문(파이프 포함)을 통째로 한 span으로 심는다.
        행 개수가 안 맞으면(예: 수식이 위첨자/아래첨자 때문에 시각적으로 2줄로
        쪼개지는데 content.text는 줄바꿈 없는 한 줄인 경우) element 전체를 하나의
        span으로 만들어 content.text 전체(줄바꿈은 공백으로 병합)를 통째로 심는다.
        이 경우 word 단위 위치 정밀도는 포기하지만 텍스트 자체는 원문 그대로 보존된다.

캐시 재사용: 057이 이미 Luenberger 42쪽(dpi=300 렌더링)에 대해 Document Parse를
호출해서 experiments/outputs/057_document_parse_scanned_ocr_compare/cache/ 아래에
응답을 캐시해뒀다. 이 실험도 동일한 dpi=300으로 같은 page를 렌더링하면 PNG bytes가
바이트 단위로 같아서 sha1 캐시 키가 일치한다 — 새로 API를 호출하지 않고 057의
캐시를 그대로 읽는다(못 찾으면 새로 호출해서 이 실험 자체 캐시에 남긴다).

출력물(사용자 요청 순서 그대로):
    1. luenberger_p042_original.pdf   : 원본 PDF에서 42쪽만 그대로 뽑아낸 1페이지 PDF
       (원본의 기존 텍스트 레이어가 있다면 그대로 남아있다 — 손대지 않는다)
    2. luenberger_p042_documentparse_overlay.pdf : 새로 만드는 산출물. 42쪽을
       300dpi로 렌더링한 이미지를 얹고, 그 위(z-order상 아래, 하지만 invisible이라
       안 보임)에 Document Parse 기반 invisible text layer를 깐다. 기존 adobeOCR
       텍스트 레이어는 여기 안 들어간다(완전히 새 페이지를 만든다).
    3. verify.json / lossless_check.txt : element별로 overlay PDF에서 다시 뽑은
       텍스트가 content.text와 (공백 정규화 후) 정확히 일치하는지 자체 검증한 결과.

실행:
    uv run python experiments/058_document_parse_pdf_overlay.py
출력:
    experiments/outputs/058_document_parse_pdf_overlay/
        - luenberger_p042_original.pdf
        - luenberger_p042.png (오버레이에 쓴 원본 렌더링 이미지)
        - luenberger_p042_documentparse_overlay.pdf
        - cache/ (057 캐시에서 못 찾을 때만 새로 호출해서 남기는 자체 캐시)
        - lossless_check.txt (element별 content.text vs 재추출 텍스트 대조)
        - verify.json
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
from ocrmypdf.font import MultiFontManager
from ocrmypdf.fpdf_renderer.renderer import Fpdf2PdfRenderer
from ocrmypdf.models.ocr_element import BoundingBox, OcrClass, OcrElement

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "058_document_parse_pdf_overlay"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
OWN_CACHE_DIR = OUTPUT_DIR / "cache"
SHARED_CACHE_DIR = (
    ROOT_DIR / "experiments" / "outputs" / "057_document_parse_scanned_ocr_compare" / "cache"
)

PDF_PATH = (
    ROOT_DIR
    / "data"
    / "scanned-pdf-indexed"
    / "David G. Luenberger, Investment Science 2nd - adobeOCR - indexed.pdf"
)
PAGE_1INDEXED = 42
RENDER_DPI = 300  # 057과 동일하게 맞춰야 캐시 sha1 키가 일치한다.

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
DIGITIZE_URL = f"{UPSTAGE_BASE_URL}/document-digitization"
MODEL = "document-parse"

LINE_GROUP_Y_TOL_FRAC = 0.006  # page height 대비 y-center 그룹핑 허용 오차(픽셀 좌표 기준)
TABLE_SEPARATOR_RE = re.compile(r"^\|?[\s:|-]+\|?$")  # markdown 표의 "| --- | --- |" 구분줄


def extract_single_page_pdf(pdf_path: Path, page_1indexed: int, out_path: Path) -> None:
    src = fitz.open(pdf_path)
    try:
        out = fitz.open()
        out.insert_pdf(src, from_page=page_1indexed - 1, to_page=page_1indexed - 1)
        out.save(str(out_path))
        out.close()
    finally:
        src.close()


def render_png_bytes(pdf_path: Path, page_1indexed: int, dpi: int = RENDER_DPI) -> tuple[bytes, int, int]:
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_1indexed - 1]
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png"), pix.width, pix.height
    finally:
        doc.close()


def _api_key() -> str:
    key = os.environ.get("UPSTAGE_API_KEY")
    if not key:
        raise RuntimeError("UPSTAGE_API_KEY가 설정되지 않았다.")
    return key


def digitize(png: bytes) -> dict[str, Any]:
    """057의 캐시를 먼저 찾아보고, 없으면 새로 호출해서 이 실험 자체 캐시에 남긴다."""
    h = hashlib.sha1(png).hexdigest()[:16]
    fname = f"{MODEL}_{h}.json"

    shared_cache = SHARED_CACHE_DIR / fname
    if shared_cache.exists():
        print(f"[cache] 057의 캐시 재사용: {shared_cache}")
        return json.loads(shared_cache.read_text(encoding="utf-8"))

    own_cache = OWN_CACHE_DIR / fname
    if own_cache.exists():
        return json.loads(own_cache.read_text(encoding="utf-8"))

    print("[api] 캐시에 없어서 Document Parse를 새로 호출한다.")
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
        OWN_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        own_cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        return out
    raise last_exc or RuntimeError("Upstage digitization 반복 429로 실패")


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def words_px_for_element(el: dict[str, Any], px_w: int, px_h: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in el.get("words") or []:
        coords = w.get("coordinates")
        text = w.get("text", "")
        if not coords or not text:
            continue
        xs = [c["x"] * px_w for c in coords]
        ys = [c["y"] * px_h for c in coords]
        out.append(
            {
                "text": text,
                "x0": min(xs),
                "x1": max(xs),
                "y0": min(ys),
                "y1": max(ys),
                "y_center": (min(ys) + max(ys)) / 2,
            }
        )
    return out


def group_words_into_lines(words: list[dict[str, Any]], px_h: int) -> list[list[dict[str, Any]]]:
    """056/057과 같은 방식: y-center 그리디 그룹핑으로 시각적 줄(행)을 복원한다."""
    y_tol = px_h * LINE_GROUP_Y_TOL_FRAC
    ordered = sorted(words, key=lambda w: (w["y_center"], w["x0"]))
    lines: list[list[dict[str, Any]]] = []
    for w in ordered:
        if lines and abs(w["y_center"] - lines[-1][-1]["y_center"]) <= y_tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    for line in lines:
        line.sort(key=lambda w: w["x0"])
    return lines


def union_bbox(words: list[dict[str, Any]]) -> BoundingBox:
    return BoundingBox(
        left=min(w["x0"] for w in words),
        top=min(w["y0"] for w in words),
        right=max(w["x1"] for w in words),
        bottom=max(w["y1"] for w in words),
    )


def line_element_from_words(words: list[dict[str, Any]]) -> OcrElement:
    """word 단위 그대로 심는다 - 기존 손실 없는 element(문단/제목 등)에 쓴다."""
    word_children = [
        OcrElement(
            ocr_class=OcrClass.WORD,
            bbox=BoundingBox(w["x0"], w["y0"], w["x1"], w["y1"]),
            text=w["text"],
        )
        for w in words
    ]
    return OcrElement(ocr_class=OcrClass.LINE, bbox=union_bbox(words), children=word_children)


def line_element_from_text(words_for_bbox: list[dict[str, Any]], text: str) -> OcrElement:
    """bbox는 word들의 union을 쓰되, 텍스트는 content.text 원문을 통째로 한 span에 심는다."""
    bbox = union_bbox(words_for_bbox)
    return OcrElement(
        ocr_class=OcrClass.LINE,
        bbox=bbox,
        children=[OcrElement(ocr_class=OcrClass.WORD, bbox=bbox, text=text)],
    )


def content_text_rows(content_text: str) -> list[str]:
    return [
        ln
        for ln in content_text.split("\n")
        if ln.strip() and not TABLE_SEPARATOR_RE.match(ln.strip())
    ]


def build_ocr_page(resp: dict[str, Any], px_w: int, px_h: int) -> tuple[OcrElement, dict[str, Any]]:
    """element마다 word-join이 content.text와 일치하면 word 단위로, 안 맞으면(표/수식 등)
    content.text 원문을 행 단위 또는 element 전체 단위로 통째로 심는다."""
    page = OcrElement(ocr_class=OcrClass.PAGE, bbox=BoundingBox(0, 0, px_w, px_h))
    stats = {"lossless_word_level": 0, "row_level_fallback": 0, "whole_element_fallback": 0, "skipped_empty": 0}

    for el in resp.get("elements", []):
        words = words_px_for_element(el, px_w, px_h)
        if not words:
            stats["skipped_empty"] += 1
            continue

        content_text = (el.get("content") or {}).get("text", "") or ""
        row_groups = group_words_into_lines(words, px_h)
        naive_join = normalize_ws(" ".join(w["text"] for row in row_groups for w in row))
        clean_join = normalize_ws(content_text)

        if naive_join == clean_join:
            stats["lossless_word_level"] += 1
            for row in row_groups:
                page.children.append(line_element_from_words(row))
            continue

        text_rows = content_text_rows(content_text)
        if len(text_rows) == len(row_groups) and text_rows:
            stats["row_level_fallback"] += 1
            for row, row_text in zip(row_groups, text_rows):
                page.children.append(line_element_from_text(row, row_text))
        else:
            stats["whole_element_fallback"] += 1
            page.children.append(line_element_from_text(words, normalize_ws(content_text)))

    return page, stats


def verify_lossless(resp: dict[str, Any], overlay_pdf_path: Path) -> tuple[str, dict[str, Any]]:
    """overlay pdf에서 element별 bbox로 텍스트를 다시 뽑아 content.text와 (공백 정규화 후) 비교한다."""
    doc = fitz.open(overlay_pdf_path)
    page = doc[0]
    page_w, page_h = page.rect.width, page.rect.height

    lines: list[str] = []
    n_match = 0
    n_total = 0
    for el in resp.get("elements", []):
        coords = el.get("coordinates")
        if not coords:
            continue
        n_total += 1
        xs = [c["x"] * page_w for c in coords]
        ys = [c["y"] * page_h for c in coords]
        rect = fitz.Rect(min(xs), min(ys), max(xs), max(ys))
        extracted = page.get_text("text", clip=rect)
        expected = (el.get("content") or {}).get("text", "") or ""
        is_match = normalize_ws(extracted) == normalize_ws(expected)
        n_match += int(is_match)

        lines.append("=" * 70)
        lines.append(f"[id={el.get('id')} category={el.get('category')} match={is_match}]")
        lines.append("-- content.text --")
        lines.append(expected)
        lines.append("-- overlay pdf에서 재추출 --")
        lines.append(extracted.strip())
        lines.append("")

    doc.close()
    summary = {"n_total": n_total, "n_match": n_match, "n_mismatch": n_total - n_match}
    return "\n".join(lines), summary


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    original_pdf_path = OUTPUT_DIR / "luenberger_p042_original.pdf"
    print(f"[extract] {PDF_PATH.name} 의 {PAGE_1INDEXED}쪽만 뽑아서 저장: {original_pdf_path.name}")
    extract_single_page_pdf(PDF_PATH, PAGE_1INDEXED, original_pdf_path)

    print(f"[render] {PAGE_1INDEXED}쪽을 {RENDER_DPI}dpi로 렌더링")
    png_bytes, px_w, px_h = render_png_bytes(PDF_PATH, PAGE_1INDEXED, RENDER_DPI)
    png_path = OUTPUT_DIR / "luenberger_p042.png"
    png_path.write_bytes(png_bytes)
    print(f"[render] {px_w}x{px_h}px 저장 완료: {png_path.name}")

    print("[document-parse] element/word 확보 중...")
    resp = digitize(png_bytes)
    print(f"[document-parse] element {len(resp.get('elements', []))}개 확보")

    print("[overlay] element별 손실 여부 판정 후 OcrElement 트리 구성")
    ocr_page, build_stats = build_ocr_page(resp, px_w, px_h)
    print(f"[overlay] {build_stats}")

    multi_font_manager = MultiFontManager()
    renderer = Fpdf2PdfRenderer(
        page=ocr_page,
        dpi=RENDER_DPI,
        multi_font_manager=multi_font_manager,
        invisible_text=True,
        image=png_path,
    )
    overlay_pdf_path = OUTPUT_DIR / "luenberger_p042_documentparse_overlay.pdf"
    renderer.render(overlay_pdf_path)
    print(f"[overlay] 저장 완료: {overlay_pdf_path.name}")

    print("[verify] element별로 재추출 텍스트를 content.text와 대조")
    check_text, verify_summary = verify_lossless(resp, overlay_pdf_path)
    (OUTPUT_DIR / "lossless_check.txt").write_text(check_text, encoding="utf-8")
    print(f"[verify] {verify_summary}")

    verify = {
        "overlay_pdf": str(overlay_pdf_path.relative_to(ROOT_DIR)),
        "build_stats": build_stats,
        "lossless_verify": verify_summary,
    }
    (OUTPUT_DIR / "verify.json").write_text(
        json.dumps(verify, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    record_experiment(build_stats, verify_summary)


def record_experiment(build_stats: dict[str, Any], verify_summary: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "[재작업] Luenberger 42쪽 overlay PDF를 만들되, 060에서 확인된 손실"
            "(표의 행/열 구분 소실, 수식의 LaTeX 구조 소실)을 없애도록 임베딩 전략을 "
            "수정했다. element마다 'word를 이어붙인 텍스트'와 'content.text'가 공백"
            "정규화 후 일치하는지 먼저 판정해서, 일치하면(문단/제목 등) 기존처럼 word "
            "단위로, 불일치하면(표/수식) content.text 원문을 행 단위 또는 element "
            "전체 단위로 통째로 심는다. ocrmypdf(17.8.0, uv pip install로 설치 - "
            "공식 문서 권장 방식이라 uv add로 pyproject.toml에 등록하지 않음)의 "
            "Fpdf2PdfRenderer/MultiFontManager/OcrElement를 그대로 재사용했다."
        ),
        "inputs": [str(PDF_PATH.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "reused_document_parse_cache_from": "057_document_parse_scanned_ocr_compare",
        "reused_library": "ocrmypdf 17.8.0 (fpdf_renderer.Fpdf2PdfRenderer, font.MultiFontManager, models.ocr_element)",
        "motivated_by": "060_overlay_text_extraction_loss_check",
        "design_note": (
            "overlay pdf는 원본 페이지의 기존(adobeOCR) 텍스트 레이어를 이어받지 않고 "
            "완전히 새 페이지(이미지+Document Parse 텍스트만)로 만들었다. 표/수식처럼 "
            "word-join과 content.text가 불일치하는 element는 word 단위 위치 정밀도 "
            "대신 content.text 원문 보존을 우선했다(행 매칭이 안 되면 element 전체를 "
            "하나의 span으로 만들어 줄바꿈만 공백으로 병합하고 텍스트는 그대로 둔다)."
        ),
        "build_stats": build_stats,
        "lossless_verify": verify_summary,
        "finding": (
            f"element {verify_summary['n_total']}개 중 {verify_summary['n_match']}개가 "
            f"overlay pdf 재추출 텍스트와 content.text가 (공백 정규화 후) 완전히 "
            f"일치했다({verify_summary['n_mismatch']}개 불일치). build_stats={build_stats} - "
            "표(row_level_fallback)와 수식(whole_element_fallback, 위첨자/아래첨자 때문에 "
            "시각적으로 2줄이라 행 개수가 안 맞아 element 전체를 한 span으로 처리됨) 모두 "
            "content.text 원문 그대로 심겼는지 lossless_check.txt에서 확인 가능하다."
        ),
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["experiments"].append(entry)
    EXPERIMENTS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
