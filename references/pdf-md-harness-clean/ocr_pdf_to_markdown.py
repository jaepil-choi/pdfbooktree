#!/usr/bin/env python3
"""OCR a scanned PDF into practical Markdown for Notion import."""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pdf_to_markdown import PAGE_BREAK, pages_to_markdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_pdf", type=Path)
    parser.add_argument("output_md", type=Path)
    parser.add_argument(
        "--engine",
        choices=("tesseract", "vision", "paddle"),
        default="paddle",
        help="OCR engine. Defaults to PaddleOCR; use vision on macOS or tesseract as fallback.",
    )
    parser.add_argument("--title", help="Markdown H1 title. Defaults to PDF filename.")
    parser.add_argument("--lang", default="eng", help="Tesseract language list, e.g. kor+eng.")
    parser.add_argument(
        "--vision-languages",
        default="ko-KR,en-US",
        help="Comma-separated macOS Vision language identifiers.",
    )
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--psm", type=int, default=3, help="Tesseract page segmentation mode.")
    parser.add_argument("--start-page", type=int, help="First page to OCR, 1-based.")
    parser.add_argument("--end-page", type=int, help="Last page to OCR, inclusive.")
    parser.add_argument(
        "--keep-page-markers",
        action="store_true",
        help="Render page markers as visible Markdown headings instead of comments.",
    )
    parser.add_argument("--pdftoppm", default="pdftoppm")
    parser.add_argument("--tesseract", default="tesseract")
    parser.add_argument("--swiftc", default="swiftc")
    parser.add_argument(
        "--paddle-python",
        type=Path,
        help="Python executable with PaddleOCR installed. If omitted, an automatic local venv is used.",
    )
    parser.add_argument(
        "--paddle-venv",
        type=Path,
        default=Path(".venv-paddle"),
        help="Virtual environment for automatic PaddleOCR installation.",
    )
    parser.add_argument(
        "--no-auto-install-paddle",
        action="store_true",
        help="Fail with installation instructions instead of installing PaddleOCR automatically.",
    )
    parser.add_argument(
        "--vision-helper",
        type=Path,
        help="Precompiled vision_ocr_batch helper. If omitted, compile the bundled Swift source.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate binaries/languages and exit without OCR.",
    )
    return parser.parse_args()


def dependency_hint(role: str) -> str:
    system = platform.system()
    if role == "pdftoppm":
        commands = {
            "Darwin": "brew install poppler",
            "Linux": "sudo apt install poppler-utils",
            "Windows": "Install Poppler for Windows and add its Library\\bin folder to PATH",
        }
    elif role == "tesseract":
        commands = {
            "Darwin": "brew install tesseract tesseract-lang",
            "Linux": "sudo apt install tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng",
            "Windows": "Install Tesseract OCR and select Korean (kor) language data",
        }
    elif role == "swiftc":
        commands = {
            "Darwin": "xcode-select --install",
            "Linux": "Vision OCR is macOS-only; use --engine tesseract",
            "Windows": "Vision OCR is macOS-only; use --engine tesseract",
        }
    elif role == "paddle":
        commands = {
            "Darwin": "python3.11 -m pip install paddleocr paddlepaddle",
            "Linux": "python3.11 -m pip install paddleocr paddlepaddle",
            "Windows": "py -3.11 -m pip install paddleocr paddlepaddle",
        }
    else:
        commands = {}
    command = commands.get(system, "See INSTALL.md for this operating system")
    guide = Path(__file__).with_name("INSTALL.md")
    return f"Install hint ({system}): {command}\nDetailed guide: {guide}"


def find_binary(name_or_path: str, role: str | None = None) -> str:
    binary = shutil.which(name_or_path)
    if binary:
        return binary
    path = Path(name_or_path)
    if path.exists() and path.is_file():
        return str(path)
    dependency = role or path.name or name_or_path
    raise SystemExit(f"Required dependency not found: {name_or_path}\n{dependency_hint(dependency)}")


def paddle_python_for_venv(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def paddle_available(python: Path) -> bool:
    proc = subprocess.run(
        [str(python), "-c", "import paddle, paddleocr"],
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def bootstrap_python_command() -> list[str]:
    """Choose a Python version supported by current PaddlePaddle wheels."""
    current = sys.version_info[:2]
    if (3, 10) <= current <= (3, 12):
        return [sys.executable]

    candidates: list[list[str]] = []
    if os.name == "nt" and shutil.which("py"):
        candidates.append(["py", "-3.11"])
    for name in ("python3.11", "python3", "python"):
        if shutil.which(name):
            candidates.append([name])
    for command in candidates:
        proc = subprocess.run(
            [*command, "-c", "import sys; print(sys.version_info[:2])"],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip() in {"(3, 10)", "(3, 11)", "(3, 12)"}:
            return command
    return [sys.executable]


def install_paddle(python: Path) -> None:
    print(f"PaddleOCR가 없어 설치합니다: {python}", flush=True)
    proc = subprocess.run(
        [str(python), "-m", "pip", "install", "--upgrade", "paddleocr", "paddlepaddle"],
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(
            "PaddleOCR 자동 설치에 실패했습니다.\n"
            f"다음 명령을 직접 실행해보세요:\n"
            f"{python} -m pip install --upgrade paddleocr paddlepaddle\n\n"
            f"{dependency_hint('paddle')}"
        )


def ensure_paddle_python(args: argparse.Namespace) -> Path:
    if args.paddle_python:
        python = args.paddle_python.expanduser()
        if not python.exists():
            raise SystemExit(f"Python executable not found: {python}\n{dependency_hint('paddle')}")
        if paddle_available(python):
            return python
        if args.no_auto_install_paddle:
            raise SystemExit(
                f"PaddleOCR is not installed in {python}.\n{dependency_hint('paddle')}"
            )
        install_paddle(python)
        if not paddle_available(python):
            raise SystemExit(f"PaddleOCR installation completed but import failed: {python}")
        return python

    current = Path(sys.executable)
    if paddle_available(current):
        return current

    venv = args.paddle_venv.expanduser()
    python = paddle_python_for_venv(venv)
    if paddle_available(python):
        return python
    if args.no_auto_install_paddle:
        raise SystemExit(
            f"PaddleOCR is not installed. Run without --no-auto-install-paddle to install it automatically.\n"
            f"{dependency_hint('paddle')}"
        )

    if not python.exists():
        bootstrap = bootstrap_python_command()
        print(f"PaddleOCR용 가상환경을 만듭니다: {venv}", flush=True)
        proc = subprocess.run(
            [*bootstrap, "-m", "venv", str(venv)],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise SystemExit(proc.stderr.strip() or f"Could not create virtual environment: {venv}")
    install_paddle(python)
    if not paddle_available(python):
        raise SystemExit(f"PaddleOCR installation completed but import failed: {python}")
    return python


def tesseract_languages(tesseract: str) -> set[str]:
    proc = subprocess.run(
        [tesseract, "--list-langs"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "Could not list Tesseract languages")
    lines = proc.stdout.splitlines()
    return {line.strip() for line in lines[1:] if line.strip()}


def validate_languages(requested: str, available: set[str]) -> None:
    required = {part for part in requested.split("+") if part}
    missing = sorted(required - available)
    if missing:
        raise SystemExit(
            "Missing Tesseract language data: "
            + ", ".join(missing)
            + "\n"
            + dependency_hint("tesseract")
        )


def page_number(path: Path) -> int:
    match = re.search(r"-(\d+)\.png$", path.name)
    return int(match.group(1)) if match else 0


def render_pages(
    input_pdf: Path,
    output_dir: Path,
    pdftoppm: str,
    dpi: int,
    start_page: int | None,
    end_page: int | None,
) -> list[Path]:
    prefix = output_dir / "page"
    cmd = [pdftoppm, "-r", str(dpi), "-png"]
    if start_page is not None:
        cmd += ["-f", str(start_page)]
    if end_page is not None:
        cmd += ["-l", str(end_page)]
    cmd += [str(input_pdf), str(prefix)]

    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "pdftoppm failed")

    pages = sorted(output_dir.glob("page-*.png"), key=page_number)
    if not pages:
        raise SystemExit("No page images were rendered")
    return pages


def ocr_page(image: Path, tesseract: str, lang: str, psm: int) -> str:
    cmd = [tesseract, str(image), "stdout", "-l", lang, "--psm", str(psm)]
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or f"Tesseract failed on {image}")
    return proc.stdout


def compile_vision_helper(source: Path, swiftc: str, output_dir: Path) -> Path:
    binary = output_dir / "vision_ocr_batch"
    swift = find_binary(swiftc, "swiftc")
    source = source.resolve()
    if not source.exists():
        raise SystemExit(f"Vision helper source not found: {source}")
    cache_dir = output_dir / "swift-module-cache"
    clang_cache_dir = output_dir / "clang-module-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    clang_cache_dir.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["SWIFT_MODULECACHE_PATH"] = str(cache_dir)
    environment["CLANG_MODULE_CACHE_PATH"] = str(clang_cache_dir)
    proc = subprocess.run(
        [swift, str(source), "-o", str(binary), "-framework", "Vision"],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "Could not compile the macOS Vision helper")
    return binary


def ocr_pages_vision(
    pages: list[Path],
    helper: Path,
    languages: str,
    output_dir: Path,
) -> list[str]:
    text_dir = output_dir / "vision-text"
    text_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(helper), "--output-dir", str(text_dir), "--languages", languages, *map(str, pages)],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "Vision OCR failed")
    texts: list[str] = []
    for page in pages:
        text_file = text_dir / f"{page.stem}.txt"
        if not text_file.exists():
            raise SystemExit(f"Vision helper did not create {text_file}")
        texts.append(text_file.read_text(encoding="utf-8", errors="replace"))
    return texts


def ocr_pages_paddle(pages: list[Path], python: Path, output_dir: Path) -> list[str]:
    runner = Path(__file__).with_name("paddle_ocr_runner.py")
    text_dir = output_dir / "paddle-text"
    text_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(python), str(runner), "--output-dir", str(text_dir), *map(str, pages)],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(
            proc.stderr.strip()
            or f"PaddleOCR failed. Install with: {dependency_hint('paddle')}"
        )
    texts: list[str] = []
    for page in pages:
        text_file = text_dir / f"{page.stem}.txt"
        if not text_file.exists():
            raise SystemExit(f"PaddleOCR did not create {text_file}")
        texts.append(text_file.read_text(encoding="utf-8", errors="replace"))
    return texts


def main() -> int:
    args = parse_args()
    if not args.input_pdf.exists():
        raise SystemExit(f"Input PDF not found: {args.input_pdf}")
    if args.dpi < 150:
        raise SystemExit("--dpi should be >= 150")
    if args.start_page is not None and args.start_page < 1:
        raise SystemExit("--start-page must be >= 1")
    if (
        args.start_page is not None
        and args.end_page is not None
        and args.end_page < args.start_page
    ):
        raise SystemExit("--end-page must be >= --start-page")

    pdftoppm = find_binary(args.pdftoppm, "pdftoppm")
    tesseract = None
    paddle_python = None
    if args.engine == "tesseract":
        tesseract = find_binary(args.tesseract, "tesseract")
        validate_languages(args.lang, tesseract_languages(tesseract))
    elif args.engine == "paddle":
        if args.check_only:
            candidates = [args.paddle_python] if args.paddle_python else [
                Path(sys.executable),
                paddle_python_for_venv(args.paddle_venv),
            ]
            paddle_python = next(
                (candidate for candidate in candidates if candidate.exists() and paddle_available(candidate)),
                candidates[0],
            )
            if not paddle_python.exists() or not paddle_available(paddle_python):
                raise SystemExit(
                    "PaddleOCR is not installed. Run without --check-only to install it automatically.\n"
                    + dependency_hint("paddle")
                )
        else:
            paddle_python = ensure_paddle_python(args)

    if args.check_only:
        print("OCR dependencies are available.")
        print(f"pdftoppm: {pdftoppm}")
        print(f"tesseract: {tesseract}")
        print(f"paddle-python: {paddle_python}")
        print(f"languages: {args.lang}")
        return 0

    title = args.title or args.input_pdf.stem
    with tempfile.TemporaryDirectory(prefix="pdf-ocr-") as tmp:
        tmp_path = Path(tmp)
        pages = render_pages(
            args.input_pdf,
            Path(tmp),
            pdftoppm,
            args.dpi,
            args.start_page,
            args.end_page,
        )
        if args.engine == "vision":
            helper = args.vision_helper
            if helper is None:
                helper = compile_vision_helper(
                    Path(__file__).with_name("vision_ocr_batch.swift"),
                    args.swiftc,
                    tmp_path / "vision-build",
                )
            texts = ocr_pages_vision(pages, helper, args.vision_languages, tmp_path)
        elif args.engine == "paddle":
            assert paddle_python is not None
            if not paddle_python.exists():
                raise SystemExit(f"Python executable not found: {paddle_python}")
            texts = ocr_pages_paddle(pages, paddle_python, tmp_path)
        else:
            assert tesseract is not None
            texts = [ocr_page(page, tesseract, args.lang, args.psm) for page in pages]

    raw_text = PAGE_BREAK.join(texts)
    markdown = pages_to_markdown(raw_text, title, args.keep_page_markers, args.start_page)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(markdown, encoding="utf-8")
    print(f"Wrote {args.output_md} ({len(markdown):,} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
