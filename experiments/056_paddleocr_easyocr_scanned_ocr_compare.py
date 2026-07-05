"""experiment 056: scanned PDF의 TOC page + 비-TOC 샘플 page에서 PaddleOCR와
EasyOCR의 실제 인식 결과를 비교한다.

배경: 기존 실험(014, 039 등)은 Upstage Document Parse의 OCR 텍스트 레이어를
그대로 신뢰했는데, 이 텍스트 자체 품질이 나쁘면 그 위에 어떤 후처리를 얹어도
scanned book의 TOC/계층 복원이 안 된다(GIGO). 이 실험은 로컬 5개 scanned PDF에
대해 (1) PDF를 렌더링한 뒤 (2) PaddleOCR와 EasyOCR을 각각 돌려서 raw 인식
결과를 사람이 눈으로 비교할 수 있는 txt로 남긴다. 정확도 판정은 하지 않고
raw text와 소요 시간만 기록한다(사람이 직접 확인).

대상 책과 TOC page range(1-based PDF page, experiments/labels/answer_toc_ranges_manual.json
및 직접 텍스트 확인으로 결정):
    - shreve_binomial: 3-11
    - luenberger_investment_science: 7-20
    - algorithm_nine: 12
    - algorithms_to_live_by: 16-19
    - suri_tonggyehak: 4-7 (라벨 파일에 없어 fitz get_text()로 직접 확인,
      "1장 확률분포" 목록이 이 4페이지에 있고 앞뒤 페이지는 서문/색인 잡음이었다)

비-TOC 샘플 page는 책마다 PDF page 42 고정(모든 책이 42페이지 이상이고 TOC
range와 겹치지 않음을 확인했다).

환경 이슈와 해결(둘 다 이 스크립트 안에서 처리, 설치 파일은 건드리지 않는다):
    1. paddleocr를 import하기 전에 torch를 먼저 import해야 한다. paddle이 먼저
       로드되면 자신의 번들 DLL을 DLL 탐색 경로에 올려서, 나중에 albumentations가
       불러오는 torch의 shm.dll 의존성 로드가 깨진다(Windows DLL 탐색 순서 문제).
    2. 이 환경의 paddlepaddle 3.3.1은 paddle.inference.Config가 기본값으로
       mkldnn(oneDNN)을 켠 채로 생성된다. paddleocr 2.10.0의 predict_det.py는
       enable_mkldnn=False일 때 disable_mkldnn()을 명시적으로 호출하지 않아서
       이 기본 설정이 그대로 유지되고, oneDNN이 예전 방식으로 export된 pretrained
       det 모델의 conv2d를 fused_conv2d로 바꾸며 "OneDnnContext does not have the
       input Filter" 에러를 낸다. paddle.inference.Config.__init__을 monkeypatch해서
       생성 직후 무조건 disable_mkldnn()을 호출하도록 만들어 우회한다.
    3. easyocr의 모델 다운로드 progress bar가 유니코드 블록 문자(█)를 출력하는데
       Windows 콘솔 기본 코드페이지(cp949)가 이를 인코딩하지 못해 죽는다.
       스크립트 시작 시 stdout을 UTF-8로 reconfigure해서 우회한다.

실행:
    uv run python experiments/056_paddleocr_easyocr_scanned_ocr_compare.py
출력:
    experiments/outputs/056_paddleocr_easyocr_scanned_ocr_compare/
        - <book_id>/toc_p<NNN>.png                  : 렌더링한 TOC page 원본 이미지
        - <book_id>/toc_p<NNN>_paddleocr.txt         : PaddleOCR 인식 결과
        - <book_id>/toc_p<NNN>_easyocr.txt           : EasyOCR 인식 결과
        - <book_id>/sample_p042.png                  : 렌더링한 비-TOC 샘플 page 원본 이미지
        - <book_id>/sample_p042_paddleocr.txt        : PaddleOCR 인식 결과
        - <book_id>/sample_p042_easyocr.txt          : EasyOCR 인식 결과
        - timing_summary.json                        : page/engine별 소요 시간과 박스 수
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# paddleocr가 albumentations -> torch를 import하기 전에 torch를 먼저 import해야
# Windows에서 torch의 shm.dll 의존성 로드가 paddle 번들 DLL과 충돌하지 않는다.
import torch  # noqa: F401,E402

import paddle.inference as _paddle_inference  # noqa: E402

_ORIG_PADDLE_CONFIG_INIT = _paddle_inference.Config.__init__


def _paddle_config_init_force_disable_mkldnn(self, *args: Any, **kwargs: Any) -> None:
    """paddle.inference.Config가 기본으로 mkldnn을 켠 채 생성되는 문제를 우회한다.

    이 환경(paddlepaddle 3.3.1)에서는 Config() 생성 직후 mkldnn_enabled()가
    이미 True다. paddleocr 2.10.0은 enable_mkldnn=False일 때 disable_mkldnn()을
    호출하지 않으므로, 예전 방식으로 export된 pretrained det 모델이 oneDNN의
    fused_conv2d 변환과 맞지 않아 추론이 깨진다. 생성자에서 무조건
    disable_mkldnn()을 호출해 이 파이프라인 한정으로 mkldnn을 끈다.
    """
    _ORIG_PADDLE_CONFIG_INIT(self, *args, **kwargs)
    self.disable_mkldnn()


_paddle_inference.Config.__init__ = _paddle_config_init_force_disable_mkldnn

import easyocr  # noqa: E402
import fitz  # noqa: E402
from paddleocr import PaddleOCR  # noqa: E402

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "056_paddleocr_easyocr_scanned_ocr_compare"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

RENDER_DPI = 300
SAMPLE_PAGE_1INDEXED = 42

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

LINE_GROUP_Y_TOL_PX = 20  # 300dpi 기준 대략 반 줄 높이. 같은 시각적 줄로 묶는 y 허용 오차.


def render_page_png(pdf_path: Path, page_1indexed: int, out_png: Path) -> None:
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_1indexed - 1]
        pix = page.get_pixmap(dpi=RENDER_DPI)
        out_png.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out_png))
    finally:
        doc.close()


def group_boxes_into_lines(
    boxes: list[dict[str, Any]], y_tol: float = LINE_GROUP_Y_TOL_PX
) -> list[list[dict[str, Any]]]:
    """box를 y좌표 기준으로 그리디하게 묶어 사람이 읽기 좋은 시각적 줄을 만든다.

    두 엔진 모두 raw 결과는 word/segment 단위로 쪼개질 수 있어서(특히
    PaddleOCR), 순수 좌표 정렬만으로는 TOC 항목이 여러 줄로 흩어져 보인다.
    정확한 줄 복원이 목적이 아니라 사람이 눈으로 훑어볼 수 있는 정도의
    reading-order 근사가 목적이므로 y-center 기준 그리디 그룹핑으로 충분하다.
    """
    ordered = sorted(boxes, key=lambda b: (b["y_center"], b["x0"]))
    lines: list[list[dict[str, Any]]] = []
    for box in ordered:
        if lines and abs(box["y_center"] - lines[-1][-1]["y_center"]) <= y_tol:
            lines[-1].append(box)
        else:
            lines.append([box])
    for line in lines:
        line.sort(key=lambda b: b["x0"])
    return lines


def format_result_txt(boxes: list[dict[str, Any]], engine: str, elapsed: float) -> str:
    lines = group_boxes_into_lines(boxes)
    out: list[str] = []
    out.append(f"# engine={engine} elapsed_sec={elapsed:.2f} boxes={len(boxes)} lines={len(lines)}")
    out.append("")
    out.append("## 읽기 순서 근사(y좌표 그리디 그룹핑, 줄 안에서는 x좌표 정렬)")
    for line in lines:
        out.append(" ".join(b["text"] for b in line))
    out.append("")
    out.append("## raw 검출 결과(y0,x0 순 정렬) - bbox / conf / text")
    for b in sorted(boxes, key=lambda b: (b["y0"], b["x0"])):
        out.append(
            f"[y0={b['y0']:.0f} y1={b['y1']:.0f} x0={b['x0']:.0f} x1={b['x1']:.0f}] "
            f"conf={b['conf']:.4f} | {b['text']}"
        )
    return "\n".join(out) + "\n"


def run_paddleocr(ocr: PaddleOCR, image_path: Path) -> tuple[list[dict[str, Any]], float]:
    t0 = time.time()
    result = ocr.ocr(str(image_path), cls=False)
    elapsed = time.time() - t0
    boxes: list[dict[str, Any]] = []
    page_result = result[0] if result else []
    for quad, (text, conf) in page_result or []:
        xs = [p[0] for p in quad]
        ys = [p[1] for p in quad]
        boxes.append(
            {
                "text": text,
                "conf": float(conf),
                "x0": min(xs),
                "x1": max(xs),
                "y0": min(ys),
                "y1": max(ys),
                "y_center": (min(ys) + max(ys)) / 2,
            }
        )
    return boxes, elapsed


def run_easyocr(reader: "easyocr.Reader", image_path: Path) -> tuple[list[dict[str, Any]], float]:
    t0 = time.time()
    result = reader.readtext(str(image_path))
    elapsed = time.time() - t0
    boxes: list[dict[str, Any]] = []
    for quad, text, conf in result:
        xs = [float(p[0]) for p in quad]
        ys = [float(p[1]) for p in quad]
        boxes.append(
            {
                "text": text,
                "conf": float(conf),
                "x0": min(xs),
                "x1": max(xs),
                "y0": min(ys),
                "y1": max(ys),
                "y_center": (min(ys) + max(ys)) / 2,
            }
        )
    return boxes, elapsed


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[init] PaddleOCR(lang=korean) 로딩 중...")
    t0 = time.time()
    paddle_ocr = PaddleOCR(lang="korean", show_log=False)
    paddle_init_sec = time.time() - t0
    print(f"[init] PaddleOCR 로딩 완료: {paddle_init_sec:.2f}s")

    print("[init] EasyOCR(['ko','en']) 로딩 중...")
    t0 = time.time()
    easy_reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
    easy_init_sec = time.time() - t0
    print(f"[init] EasyOCR 로딩 완료: {easy_init_sec:.2f}s")

    timing: dict[str, Any] = {
        "paddleocr_init_sec": paddle_init_sec,
        "easyocr_init_sec": easy_init_sec,
        "render_dpi": RENDER_DPI,
        "pages": [],
    }

    run_started = time.time()

    for book_id, meta in BOOKS.items():
        pdf_path: Path = meta["path"]
        toc_pages: list[int] = meta["toc_pages"]
        book_dir = OUTPUT_DIR / book_id

        targets: list[tuple[str, int]] = [("toc", p) for p in toc_pages]
        targets.append(("sample", SAMPLE_PAGE_1INDEXED))

        for kind, page_no in targets:
            tag = f"{kind}_p{page_no:03d}"
            png_path = book_dir / f"{tag}.png"
            print(f"[render] {book_id} {tag} -> {png_path.name}")
            render_page_png(pdf_path, page_no, png_path)

            print(f"[paddleocr] {book_id} {tag} 처리 중...")
            paddle_boxes, paddle_elapsed = run_paddleocr(paddle_ocr, png_path)
            (book_dir / f"{tag}_paddleocr.txt").write_text(
                format_result_txt(paddle_boxes, "paddleocr", paddle_elapsed),
                encoding="utf-8",
            )
            print(f"[paddleocr] {book_id} {tag} 완료: {paddle_elapsed:.2f}s, boxes={len(paddle_boxes)}")

            print(f"[easyocr] {book_id} {tag} 처리 중...")
            easy_boxes, easy_elapsed = run_easyocr(easy_reader, png_path)
            (book_dir / f"{tag}_easyocr.txt").write_text(
                format_result_txt(easy_boxes, "easyocr", easy_elapsed),
                encoding="utf-8",
            )
            print(f"[easyocr] {book_id} {tag} 완료: {easy_elapsed:.2f}s, boxes={len(easy_boxes)}")

            timing["pages"].append(
                {
                    "book_id": book_id,
                    "kind": kind,
                    "page_1indexed": page_no,
                    "paddleocr_sec": paddle_elapsed,
                    "paddleocr_boxes": len(paddle_boxes),
                    "easyocr_sec": easy_elapsed,
                    "easyocr_boxes": len(easy_boxes),
                }
            )

    total_elapsed = time.time() - run_started
    timing["total_ocr_loop_sec"] = total_elapsed
    timing["total_pages"] = len(timing["pages"])
    timing["total_paddleocr_sec"] = sum(p["paddleocr_sec"] for p in timing["pages"])
    timing["total_easyocr_sec"] = sum(p["easyocr_sec"] for p in timing["pages"])

    (OUTPUT_DIR / "timing_summary.json").write_text(
        json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"[done] pages={timing['total_pages']} "
        f"paddleocr_total={timing['total_paddleocr_sec']:.1f}s "
        f"easyocr_total={timing['total_easyocr_sec']:.1f}s "
        f"loop_total={total_elapsed:.1f}s"
    )

    record_experiment(timing)


def record_experiment(timing: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "scanned PDF(5권)의 TOC page range 전체 + 책마다 비-TOC 샘플 page(42쪽)를 "
            "300dpi로 렌더링한 뒤 PaddleOCR(lang=korean)과 EasyOCR(['ko','en'])을 "
            "각각 돌려 raw 인식 결과와 소요 시간을 비교한다. 기존 파이프라인이 의존하던 "
            "OCR 텍스트 레이어 품질 자체가 병목(GIGO)이라는 가설 위에서, 두 로컬 OCR "
            "엔진이 대안이 될 수 있는지 사람이 직접 눈으로 볼 수 있는 txt를 남긴다. "
            "정확도 판정은 사람이 결과 txt를 보고 직접 내린다(이 실험은 판정하지 않는다)."
        ),
        "inputs": [str(meta["path"].relative_to(ROOT_DIR)) for meta in BOOKS.values()],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "toc_page_ranges": {
            book_id: {"toc_pages": meta["toc_pages"], "sample_page": SAMPLE_PAGE_1INDEXED}
            for book_id, meta in BOOKS.items()
        },
        "render_dpi": RENDER_DPI,
        "paddleocr_lang": "korean",
        "easyocr_langs": ["ko", "en"],
        "environment_workarounds": [
            "paddleocr import 전에 torch를 먼저 import해서 Windows DLL 탐색 순서 충돌(shm.dll) 회피",
            "paddle.inference.Config.__init__을 monkeypatch해서 생성 직후 disable_mkldnn() 강제 호출"
            "(paddlepaddle 3.3.1이 기본으로 mkldnn on 상태라 예전 export 모델의 fused_conv2d와 충돌하는 문제 우회)",
            "sys.stdout을 UTF-8로 reconfigure해서 easyocr 모델 다운로드 progress bar의 유니코드 블록 문자로 인한 cp949 크래시 회피",
        ],
        "timing_summary": {
            "paddleocr_init_sec": timing["paddleocr_init_sec"],
            "easyocr_init_sec": timing["easyocr_init_sec"],
            "total_pages": timing["total_pages"],
            "total_paddleocr_sec": timing["total_paddleocr_sec"],
            "total_easyocr_sec": timing["total_easyocr_sec"],
            "avg_paddleocr_sec_per_page": timing["total_paddleocr_sec"] / timing["total_pages"],
            "avg_easyocr_sec_per_page": timing["total_easyocr_sec"] / timing["total_pages"],
        },
        "finding": (
            "PENDING: 소요 시간만 자동 기록했고, 인식 품질은 사람이 outputs/의 txt를 "
            "직접 눈으로 확인해서 판단해야 한다."
        ),
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["experiments"].append(entry)
    EXPERIMENTS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
