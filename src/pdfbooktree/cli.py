"""Typer 기반 CLI entrypoint다."""

from __future__ import annotations

from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import cast

import fitz
import typer
from rich import print as rich_print

from pdfbooktree.artifacts import write_artifact, write_inference_artifacts
from pdfbooktree.batch import BatchProcessor
from pdfbooktree.classify import (
    ClassifyBatchConfig,
    ClassifyLogMode,
    ScanBookmarkClassifier,
    build_classify_logger,
    default_classify_log_mode,
)
from pdfbooktree.cli_contract import (
    CLI_EXIT_INPUT_ERROR,
    CLI_EXIT_PROCESSING_FAILED,
    CLI_EXIT_RUNTIME_ERROR,
    OutputFormat,
    ProcessingFailedError,
    emit_command_result,
    exit_command_error,
    parse_output_format,
)
from pdfbooktree.config import ConfigError, ProcessingConfig
from pdfbooktree.config_io import (
    config_field_specs,
    config_schema,
    render_config_toml,
    resolve_processing_config,
    write_config_template,
)
from pdfbooktree.inspection import (
    inspect_bookmarks,
    inspect_ocr_artifact,
    inspect_page_count,
    inspect_plan_artifact,
    inspect_text,
)
from pdfbooktree.models import BookmarkPlanItem, ConfidenceSummary, ProcessingResult
from pdfbooktree.ocr import (
    ExistingBookmarkConfirmationRequired,
    OcrOverlayBatchConfig,
    OcrOverlayBatchRunner,
    OcrOverlayBuilder,
    OcrOverlayConfig,
)
from pdfbooktree.ocr.config import CachePolicy
from pdfbooktree.ocr.logger import OcrLogMode, build_ocr_logger, default_ocr_log_mode
from pdfbooktree.outline.plan_io import PlanError, load_bookmark_plan_json
from pdfbooktree.outline.validate import validate_bookmark_plan
from pdfbooktree.pdf.outline import outline_to_plan
from pdfbooktree.pdf.scan_signals import DEFAULT_MAX_SAMPLE_PAGES
from pdfbooktree.pipeline import (
    analyze_pdf,
    apply_plan,
    confidence_summary_for_inference,
    infer_bookmarks,
    resolve_existing_outline_action,
)
from pdfbooktree.processor import Processor
from pdfbooktree.report import write_processing_report
from pdfbooktree.run import RunError, create_run_context
from pdfbooktree.utils.hashing import file_sha256
from pdfbooktree.utils.jsonio import to_jsonable

app = typer.Typer(
    help="PDF 책의 typography hierarchy로 bookmark와 Markdown tree를 만든다."
)
inspect_app = typer.Typer(help="PDF와 처리 artifact를 읽기 전용으로 조사한다.")
config_app = typer.Typer(help="versioned processing config를 생성하고 검증한다.")
app.add_typer(inspect_app, name="inspect")
app.add_typer(config_app, name="config")


def _stage_output_format(value: str) -> OutputFormat:
    """단계형 command의 출력 형식을 Typer 입력 오류로 검증한다."""

    try:
        return parse_output_format(value)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def _exit_stage_input_error(
    command: str,
    error: Exception,
    *,
    code: str,
    output_format: OutputFormat,
) -> None:
    """단계형 command의 config/plan/input 오류를 exit 2로 끝낸다."""

    exit_command_error(
        command,
        error,
        code=code,
        exit_code=CLI_EXIT_INPUT_ERROR,
        output_format=output_format,
    )


def _validate_flat_input_pdf(
    command: str,
    pdf: Path,
    *,
    output_format: OutputFormat,
) -> None:
    """manifest가 없는 flat mode에서도 PDF 입력 오류를 exit 2로 통일한다."""

    input_path = pdf.resolve()
    if not input_path.is_file():
        _exit_stage_input_error(
            command,
            RunError(f"입력 PDF가 없다: {input_path}"),
            code="invalid_input",
            output_format=output_format,
        )
    try:
        with fitz.open(input_path):
            pass
    except (fitz.FileDataError, RuntimeError) as error:
        _exit_stage_input_error(
            command,
            RunError(f"입력 PDF를 열지 못했다: {input_path}, reason={error}"),
            code="invalid_input",
            output_format=output_format,
        )


def _exit_stage_runtime_error(
    command: str,
    error: Exception,
    *,
    output_format: OutputFormat,
    debug: bool,
) -> None:
    """예상하지 못한 runtime 오류를 숨기거나 debug에서 다시 발생시킨다."""

    if debug:
        raise error
    exit_command_error(
        command,
        error,
        code="runtime_error",
        exit_code=CLI_EXIT_RUNTIME_ERROR,
        output_format=output_format,
    )


def _emit_stage_result(
    command: str,
    payload: object,
    processing_result: ProcessingResult,
    *,
    output_format: OutputFormat,
) -> None:
    """단계형 command의 성공 또는 validation 실패 결과를 출력한다."""

    if processing_result.status == "failed":
        error = ProcessingFailedError(
            f"{command} pipeline이 유효한 결과를 만들지 못했다."
        )
        exit_command_error(
            command,
            error,
            code="processing_failed",
            exit_code=CLI_EXIT_PROCESSING_FAILED,
            output_format=output_format,
            details=payload,
        )
    emit_command_result(command, payload, output_format=output_format)


@config_app.command("defaults")
def config_defaults_cmd(
    output_format: str = typer.Option(
        "human", "--format", help="출력 형식이다: human, json."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """현재 package의 resolved 기본 config를 출력한다."""

    resolved_output_format = _stage_output_format(output_format)
    try:
        resolved = resolve_processing_config()
    except ConfigError as error:
        _exit_stage_input_error(
            "config.defaults",
            error,
            code="invalid_config",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            "config.defaults",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    value: object = (
        resolved.data
        if resolved_output_format == "json"
        else render_config_toml(resolved.config)
    )
    emit_command_result("config.defaults", value, output_format=resolved_output_format)


@config_app.command("schema")
def config_schema_cmd(
    output_format: str = typer.Option(
        "json", "--format", help="출력 형식이다: human, json."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """public config의 JSON Schema를 출력한다."""

    resolved_output_format = _stage_output_format(output_format)
    try:
        value = config_schema()
    except Exception as error:
        _exit_stage_runtime_error(
            "config.schema",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    emit_command_result("config.schema", value, output_format=resolved_output_format)


@config_app.command("init")
def config_init_cmd(
    path: Path = typer.Argument(..., help="생성할 TOML config 경로다."),
    force: bool = typer.Option(
        False, "--force", help="config 파일이 이미 있어도 덮어쓴다."
    ),
    output_format: str = typer.Option(
        "human", "--format", help="출력 형식이다: human, json."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """주석이 포함된 기본 TOML config 파일을 만든다."""

    resolved_output_format = _stage_output_format(output_format)
    try:
        created = write_config_template(path, force=force)
    except ConfigError as error:
        _exit_stage_input_error(
            "config.init",
            error,
            code="invalid_config",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            "config.init",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    emit_command_result(
        "config.init",
        {"status": "created", "config_path": str(created)},
        output_format=resolved_output_format,
    )


@config_app.command("explain")
def config_explain_cmd(
    key: str | None = typer.Argument(
        None, help="설명할 dotted config key다. 생략하면 전체 field를 출력한다."
    ),
    output_format: str = typer.Option(
        "human", "--format", help="출력 형식이다: human, json."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """config field의 타입, 기본값, 범위와 설명을 출력한다."""

    resolved_output_format = _stage_output_format(output_format)
    try:
        specs = config_field_specs()
        if key is not None:
            if key not in specs:
                raise ConfigError(f"알 수 없는 config key다: {key}")
            value: object = {"key": key, **specs[key]}
        else:
            value = specs
    except ConfigError as error:
        _exit_stage_input_error(
            "config.explain",
            error,
            code="invalid_config",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            "config.explain",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    emit_command_result("config.explain", value, output_format=resolved_output_format)


@config_app.command("validate")
def config_validate_cmd(
    path: Path = typer.Argument(..., help="검증할 TOML config 경로다."),
    set_option: list[str] = typer.Option(
        [],
        "--set",
        help="최종 config override다. dotted.key=value 형식으로 여러 번 줄 수 있다.",
    ),
    output_format: str = typer.Option(
        "human", "--format", help="출력 형식이다: human, json."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """TOML과 override를 합친 resolved config를 검증한다."""

    resolved_output_format = _stage_output_format(output_format)
    try:
        resolved = resolve_processing_config(path, set_overrides=set_option)
    except ConfigError as error:
        _exit_stage_input_error(
            "config.validate",
            error,
            code="invalid_config",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            "config.validate",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    emit_command_result(
        "config.validate",
        {
            "status": "valid",
            "config_path": str(path),
            "config_hash": resolved.config_hash,
            "resolved_config": resolved.data,
            "sources": resolved.sources,
        },
        output_format=resolved_output_format,
    )


def parse_page_ranges(value: str | None) -> list[int] | None:
    """CLI의 1-3,42 형태 page range 문자열을 1-based page 목록으로 바꾼다."""

    if value is None or not value.strip():
        return None
    pages: list[int] = []
    for part in value.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start > end:
                raise typer.BadParameter(f"page range 시작이 끝보다 크다: {token}")
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(token))
    if any(page < 1 for page in pages):
        raise typer.BadParameter("PDF page는 1 이상이어야 한다.")
    return sorted(dict.fromkeys(pages))


def parse_engine_options(values: list[str]) -> dict[str, object]:
    """--engine-option key=value 목록을 dict로 변환한다."""

    options: dict[str, object] = {}
    for value in values:
        if "=" not in value:
            raise typer.BadParameter("--engine-option은 key=value 형식이어야 한다.")
        key, raw = value.split("=", 1)
        key = key.strip()
        if not key:
            raise typer.BadParameter("--engine-option key가 비어 있다.")
        options[key] = _coerce_engine_option_value(raw.strip())
    return options


def _inspection_output_format(value: str, *, as_json: bool) -> OutputFormat:
    """canonical format을 검증하고 기존 ``--json`` alias를 적용한다."""

    resolved = _stage_output_format(value)
    return "json" if as_json else resolved


@inspect_app.command("page-count")
def inspect_page_count_cmd(
    pdf: Path = typer.Argument(..., help="확인할 PDF 파일이다."),
    output_format: str = typer.Option(
        "human", "--format", help="출력 형식이다: human, json."
    ),
    as_json: bool = typer.Option(
        False, "--json", help="호환 alias다. --format json과 같다."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """PDF 총 page 수를 확인한다."""

    resolved_output_format = _inspection_output_format(output_format, as_json=as_json)
    try:
        result = inspect_page_count(pdf)
    except (FileNotFoundError, ValueError) as error:
        _exit_stage_input_error(
            "inspect.page-count",
            error,
            code="invalid_input",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            "inspect.page-count",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    emit_command_result(
        "inspect.page-count", result, output_format=resolved_output_format
    )


@inspect_app.command("text")
def inspect_text_cmd(
    pdf: Path = typer.Argument(..., help="확인할 PDF 파일이다."),
    pages: str = typer.Option(..., "--pages", help="1-based page 목록이다. 예: 1-3,42"),
    output_format: str = typer.Option(
        "human", "--format", help="출력 형식이다: human, json."
    ),
    as_json: bool = typer.Option(
        False, "--json", help="호환 alias다. --format json과 같다."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """지정한 1-based page 범위의 text를 확인한다."""

    resolved_output_format = _inspection_output_format(output_format, as_json=as_json)
    try:
        parsed_pages = parse_page_ranges(pages)
        if parsed_pages is None:
            raise ValueError("확인할 PDF page를 하나 이상 지정해야 한다.")
        result = inspect_text(pdf, parsed_pages)
    except (FileNotFoundError, ValueError, typer.BadParameter) as error:
        _exit_stage_input_error(
            "inspect.text",
            error,
            code="invalid_input",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            "inspect.text",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    emit_command_result("inspect.text", result, output_format=resolved_output_format)


@inspect_app.command("bookmarks")
def inspect_bookmarks_cmd(
    pdf: Path = typer.Argument(..., help="확인할 PDF 파일이다."),
    output_format: str = typer.Option(
        "human", "--format", help="출력 형식이다: human, json."
    ),
    as_json: bool = typer.Option(
        False, "--json", help="호환 alias다. --format json과 같다."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """PDF의 기존 bookmark를 확인한다."""

    resolved_output_format = _inspection_output_format(output_format, as_json=as_json)
    try:
        result = inspect_bookmarks(pdf)
    except (FileNotFoundError, ValueError) as error:
        _exit_stage_input_error(
            "inspect.bookmarks",
            error,
            code="invalid_input",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            "inspect.bookmarks",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    emit_command_result(
        "inspect.bookmarks", result, output_format=resolved_output_format
    )


@inspect_app.command("ocr")
def inspect_ocr_cmd(
    artifact_dir: Path = typer.Argument(..., help="OCR artifact directory다."),
    output_format: str = typer.Option(
        "human", "--format", help="출력 형식이다: human, json."
    ),
    as_json: bool = typer.Option(
        False, "--json", help="호환 alias다. --format json과 같다."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """OCR 진행 상태, cache, stats와 마지막 log event를 확인한다."""

    resolved_output_format = _inspection_output_format(output_format, as_json=as_json)
    try:
        result = inspect_ocr_artifact(artifact_dir)
    except (FileNotFoundError, ValueError) as error:
        _exit_stage_input_error(
            "inspect.ocr",
            error,
            code="invalid_input",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            "inspect.ocr",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    emit_command_result("inspect.ocr", result, output_format=resolved_output_format)


@inspect_app.command("plan")
def inspect_plan_cmd(
    output_dir: Path = typer.Argument(..., help="process output directory다."),
    output_format: str = typer.Option(
        "human", "--format", help="출력 형식이다: human, json."
    ),
    as_json: bool = typer.Option(
        False, "--json", help="호환 alias다. --format json과 같다."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """bookmark plan validation과 Markdown export 결과를 확인한다."""

    resolved_output_format = _inspection_output_format(output_format, as_json=as_json)
    try:
        result = inspect_plan_artifact(output_dir)
    except (FileNotFoundError, ValueError) as error:
        _exit_stage_input_error(
            "inspect.plan",
            error,
            code="invalid_input",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            "inspect.plan",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    emit_command_result("inspect.plan", result, output_format=resolved_output_format)


def _coerce_engine_option_value(value: str) -> object:
    if "," in value:
        return [
            _coerce_engine_option_value(part.strip())
            for part in value.split(",")
            if part.strip()
        ]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _legacy_process_cli_overrides(
    context: typer.Context, values: dict[str, object]
) -> dict[str, object]:
    """기존 process flag 중 command line에서 명시한 값만 config override로 만든다."""

    field_map = {
        "skip_existing_bookmarks": "processing.skip_existing_bookmarks",
        "heading_candidate_mode": "typography.heading_candidate_mode",
        "body_font_text_coverage": "typography.body_font_text_coverage",
        "body_font_max_words": "typography.body_font_max_words",
        "position_min_repeated_pages": "typography.position_min_repeated_pages",
        "position_fallback_enabled": "typography.position_fallback_enabled",
        "position_fallback_tolerance": "typography.position_fallback_tolerance",
        "position_fallback_min_isolation_ratio": (
            "typography.position_fallback_min_isolation_ratio"
        ),
        "min_tier_count": "typography.min_tier_count",
        "max_heading_tier": "typography.max_heading_tier",
        "bpe_max_node_words": "typography.bpe_max_node_words",
        "bpe_level_pollution_ratio": "typography.bpe_level_pollution_ratio",
        "margin_band_ratio": "typography.margin_band_ratio",
        "margin_min_consecutive_pages": "typography.margin_min_consecutive_pages",
        "max_words": "markdown.max_words",
        "max_words_coverage": "markdown.max_words_coverage",
    }
    overrides: dict[str, object] = {}
    for parameter_name, dotted_key in field_map.items():
        source = context.get_parameter_source(parameter_name)
        if source is None or getattr(source, "name", None) != "COMMANDLINE":
            continue
        value = values[parameter_name]
        if value is not None:
            overrides[dotted_key] = value
    return overrides


@app.command()
def ocr_overlay(
    pdf: Path = typer.Argument(..., help="OCR overlay를 만들 PDF 파일이다."),
    output_pdf: Path = typer.Option(
        ..., "--output", "-o", help="생성할 searchable OCR PDF 경로다."
    ),
    output_dir: Path = typer.Option(
        ..., "--output-dir", help="OCR cache와 stats artifact를 저장할 디렉터리다."
    ),
    engine: str = typer.Option("upstage", "--engine", help="OCR engine 이름이다."),
    render_dpi: int = typer.Option(300, "--render-dpi", min=72, help="렌더링 DPI다."),
    pages: str | None = typer.Option(
        None, "--pages", help="처리할 1-based page 목록이다. 예: 1-3,42"
    ),
    force: bool = typer.Option(
        False, "--force", help="출력 PDF가 이미 있어도 덮어쓴다."
    ),
    confirm_bookmark_ocr_overwrite: bool = typer.Option(
        False,
        "--confirm-bookmark-ocr-overwrite",
        help="기존 bookmark가 있는 PDF의 OCR text layer 교체를 명시적으로 확인한다.",
    ),
    cache_policy: str = typer.Option(
        "reuse",
        "--cache-policy",
        help=(
            "OCR raw/insertable cache 사용 방식이다. reuse(있으면 재사용, 없으면 "
            "호출), refresh(항상 새로 호출), only(cache만 쓰고 없으면 실패, API "
            "호출 안 함) 중 하나다."
        ),
    ),
    stats_word_level: bool = typer.Option(
        False, "--stats-word-level", help="word 단위 stats artifact도 저장한다."
    ),
    engine_option: list[str] = typer.Option(
        [],
        "--engine-option",
        help="OCR engine option이다. key=value 형식이며 여러 번 줄 수 있다.",
    ),
    log_mode: str = typer.Option(
        "auto",
        "--log-mode",
        help="OCR runtime 로그 출력 방식이다. auto, tqdm, plain, json, none 중 하나다.",
    ),
    no_log_file: bool = typer.Option(
        False,
        "--no-log-file",
        help="ocr_log.jsonl과 ocr_progress.json 파일 기록을 끈다.",
    ),
    output_format: str = typer.Option(
        "human", "--format", help="최종 결과 출력 형식이다: human, json."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """PDF 모든 page를 OCR parse한 뒤 invisible text layer를 다시 입힌다."""

    command = "ocr-overlay"
    resolved_output_format = _stage_output_format(output_format)
    resolved_log_mode = default_ocr_log_mode() if log_mode == "auto" else log_mode
    if resolved_log_mode not in {"tqdm", "plain", "json", "none"}:
        _exit_stage_input_error(
            command,
            ValueError("log-mode은 auto, tqdm, plain, json, none 중 하나여야 한다."),
            code="invalid_input",
            output_format=resolved_output_format,
        )
    if cache_policy not in {"reuse", "refresh", "only"}:
        _exit_stage_input_error(
            command,
            ValueError("cache-policy는 reuse, refresh, only 중 하나여야 한다."),
            code="invalid_input",
            output_format=resolved_output_format,
        )
    try:
        logger = build_ocr_logger(
            cast(OcrLogMode, resolved_log_mode),
            output_dir,
            enable_file=not no_log_file,
            desc=f"OCR overlay: {pdf.name}",
        )
        config = OcrOverlayConfig(
            input_pdf=pdf,
            output_pdf=output_pdf,
            output_dir=output_dir,
            engine=engine,
            engine_options=parse_engine_options(engine_option),
            render_dpi=render_dpi,
            pages=parse_page_ranges(pages),
            force=force,
            confirm_bookmark_ocr_overwrite=confirm_bookmark_ocr_overwrite,
            cache_policy=cast(CachePolicy, cache_policy),
            stats_word_level=stats_word_level,
        )
        result = OcrOverlayBuilder(config, logger=logger).run()
    except (
        ExistingBookmarkConfirmationRequired,
        FileExistsError,
        FileNotFoundError,
        typer.BadParameter,
        ValueError,
    ) as error:
        _exit_stage_input_error(
            command,
            error,
            code="invalid_input",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            command,
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    payload = {
        "status": result.status,
        "page_count": result.page_count,
        "processed_page_count": len(result.processed_pages),
        "cache_hit_count": result.cache_hit_count,
        "cache_miss_count": result.cache_miss_count,
        "output_pdf": result.output_pdf,
        "output_dir": result.output_dir,
        "page_stats_path": result.page_stats_path,
    }
    if result.status == "failed":
        exit_command_error(
            command,
            ProcessingFailedError("ocr-overlay pipeline이 처리 결과를 만들지 못했다."),
            code="processing_failed",
            exit_code=CLI_EXIT_PROCESSING_FAILED,
            output_format=resolved_output_format,
            details=payload,
        )
    emit_command_result(command, payload, output_format=resolved_output_format)


@app.command("ocr-overlay-batch")
def ocr_overlay_batch_cmd(
    input_dir: Path = typer.Argument(..., help="PDF를 찾을 입력 디렉터리다."),
    output_dir: Path = typer.Option(
        ..., "--output-dir", "-o", help="OCR batch 산출물을 저장할 디렉터리다."
    ),
    recursive: bool = typer.Option(
        False, "--recursive", "-r", help="하위 디렉터리까지 찾는다."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="target 판정과 report만 만들고 OCR API 호출과 PDF 생성을 하지 않는다.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="출력 PDF가 이미 있어도 덮어쓴다. 기본값은 기존 output을 skip한다.",
    ),
    confirm_bookmark_ocr_overwrite: bool = typer.Option(
        False,
        "--confirm-bookmark-ocr-overwrite",
        help="기존 bookmark가 있는 target PDF의 OCR text layer 교체를 명시적으로 확인한다.",
    ),
    engine: str = typer.Option("upstage", "--engine", help="OCR engine 이름이다."),
    render_dpi: int = typer.Option(300, "--render-dpi", min=72, help="렌더링 DPI다."),
    max_sample_pages: int = typer.Option(
        DEFAULT_MAX_SAMPLE_PAGES,
        "--max-sample-pages",
        min=1,
        help="target 판정을 위해 문서당 sampling할 최대 page 수다.",
    ),
    stats_word_level: bool = typer.Option(
        False, "--stats-word-level", help="word 단위 stats artifact도 저장한다."
    ),
    engine_option: list[str] = typer.Option(
        [],
        "--engine-option",
        help="OCR engine option이다. key=value 형식이며 여러 번 줄 수 있다.",
    ),
    log_mode: str = typer.Option(
        "auto",
        "--log-mode",
        help=(
            "OCR runtime 로그 출력 방식이다. auto, tqdm, plain, json, none 중 하나다. "
            "tqdm은 전체 batch page 진행(outer bar)과 현재 책 page 진행(inner bar)을 "
            "함께 보여주고, 남은 시간은 전체 대상 page 수 기준으로 추정한다."
        ),
    ),
    no_log_file: bool = typer.Option(
        False,
        "--no-log-file",
        help="파일별 ocr_log.jsonl과 ocr_progress.json 기록을 끈다.",
    ),
) -> None:
    """디렉터리 안 target PDF만 골라 OCR overlay를 batch 실행한다."""

    resolved_log_mode = default_ocr_log_mode() if log_mode == "auto" else log_mode
    if resolved_log_mode not in {"tqdm", "plain", "json", "none"}:
        raise typer.BadParameter(
            "log-mode은 auto, tqdm, plain, json, none 중 하나여야 한다."
        )
    config = OcrOverlayBatchConfig(
        input_dir=input_dir,
        output_dir=output_dir,
        recursive=recursive,
        dry_run=dry_run,
        force=force,
        confirm_bookmark_ocr_overwrite=confirm_bookmark_ocr_overwrite,
        engine=engine,
        engine_options=parse_engine_options(engine_option),
        render_dpi=render_dpi,
        max_sample_pages=max_sample_pages,
        stats_word_level=stats_word_level,
    )
    runner = OcrOverlayBatchRunner(
        config,
        log_mode=cast(OcrLogMode, resolved_log_mode),
        enable_log_file=not no_log_file,
    )
    result = runner.run()
    rich_print(
        to_jsonable(
            {
                "total_pdf_count": result.total_pdf_count,
                "target_count": result.target_count,
                "processed_count": result.processed_count,
                "dry_run_count": result.dry_run_count,
                "skipped_count": result.skipped_count,
                "failed_count": result.failed_count,
                "elapsed_sec": result.elapsed_sec,
                "report_csv_path": result.report_csv_path,
                "detail_jsonl_path": result.detail_jsonl_path,
                "summary_path": result.summary_path,
            }
        )
    )


@app.command()
def process(
    context: typer.Context,
    pdf: Path = typer.Argument(..., help="처리할 PDF 파일이다."),
    output_dir: Path = typer.Option(
        Path("."),
        "--output-dir",
        "-o",
        help="run directory를 만들 output root다.",
    ),
    config_path: Path | None = typer.Option(
        None, "--config", help="읽을 versioned TOML processing config다."
    ),
    set_option: list[str] = typer.Option(
        [],
        "--set",
        help="최종 config override다. dotted.key=value 형식으로 여러 번 줄 수 있다.",
    ),
    flat_output: bool = typer.Option(
        False,
        "--flat-output",
        help="호환을 위해 immutable run directory 없이 기존 flat output을 사용한다.",
    ),
    skip_existing_bookmarks: bool = typer.Option(
        True,
        "--skip-existing-bookmarks/--no-skip-existing-bookmarks",
        help="기존 outline이 있으면 typography 추론 대신 Markdown export만 수행한다.",
    ),
    heading_candidate_mode: str = typer.Option(
        "font",
        "--heading-candidate-mode",
        help="heading 후보 필터다: position, font, position_and_font.",
    ),
    body_font_text_coverage: float = typer.Option(
        0.95,
        "--body-font-text-coverage",
        min=0.01,
        max=1.0,
        help="text length 누적으로 본문 font tier를 포함할 목표 비율이다.",
    ),
    body_font_max_words: int = typer.Option(
        20,
        "--body-font-max-words",
        min=1,
        help="font 골격 heading 후보로 볼 최대 단어 수다.",
    ),
    position_min_repeated_pages: int = typer.Option(
        5,
        "--position-min-repeated-pages",
        min=1,
        help="동일 anchor pattern이 반복되어야 하는 최소 page 수다.",
    ),
    position_fallback_enabled: bool = typer.Option(
        True,
        "--position-fallback/--no-position-fallback",
        help="font tier에 흡수된 body-tier heading을 반복 위치로 rescue한다.",
    ),
    position_fallback_tolerance: float = typer.Option(
        2.0,
        "--position-fallback-tolerance",
        min=0.1,
        help="body-tier position fallback의 current-anchor 2D 허용 오차다.",
    ),
    position_fallback_min_isolation_ratio: float = typer.Option(
        1.0,
        "--position-fallback-min-isolation-ratio",
        min=0.0,
        help="다른 반복 위치 cluster로부터 최소 이 배수만큼 떨어져야 한다.",
    ),
    min_tier_count: int = typer.Option(
        5,
        "--min-tier-count",
        min=1,
        help="희소 typography tier를 병합하기 위한 최소 line 수다.",
    ),
    max_heading_tier: int = typer.Option(
        3, "--max-heading-tier", min=1, help="heading 후보로 볼 최대 tier 번호다."
    ),
    bpe_max_node_words: int = typer.Option(
        30,
        "--bpe-max-node-words",
        min=1,
        help="이 단어 수를 초과한 BPE node는 hierarchy를 한 단계 낮춘다.",
    ),
    bpe_level_pollution_ratio: float = typer.Option(
        0.30,
        "--bpe-level-pollution-ratio",
        min=0.0,
        max=1.0,
        help="장문 BPE node 비율이 이 값보다 큰 bookmark level은 본문으로 제외한다.",
    ),
    margin_band_ratio: float = typer.Option(
        0.12,
        "--margin-band-ratio",
        min=0.01,
        max=0.25,
        help="반복 header/footer를 찾을 page 상·하단 영역 비율이다.",
    ),
    margin_min_consecutive_pages: int = typer.Option(
        10,
        "--margin-min-consecutive-pages",
        min=2,
        help="인쇄 쪽수 offset이 연속으로 유지되어야 하는 최소 page 수다.",
    ),
    max_words: int | None = typer.Option(
        None,
        "--max-words",
        min=1,
        help="지정하면 coverage 기반 단일 Markdown split export를 활성화한다.",
    ),
    max_words_coverage: float = typer.Option(
        0.95,
        "--max-words-coverage",
        min=0.01,
        max=1.0,
        help="max-words 이하가 되어야 하는 Markdown 파일 비율이다.",
    ),
    output_format: str = typer.Option(
        "human", "--format", help="final result 출력 형식이다: human, json."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """단일 PDF를 typography hierarchy 기반으로 처리한다."""

    resolved_output_format = _stage_output_format(output_format)
    legacy_values: dict[str, object] = {
        "skip_existing_bookmarks": skip_existing_bookmarks,
        "heading_candidate_mode": heading_candidate_mode,
        "body_font_text_coverage": body_font_text_coverage,
        "body_font_max_words": body_font_max_words,
        "position_min_repeated_pages": position_min_repeated_pages,
        "position_fallback_enabled": position_fallback_enabled,
        "position_fallback_tolerance": position_fallback_tolerance,
        "position_fallback_min_isolation_ratio": (
            position_fallback_min_isolation_ratio
        ),
        "min_tier_count": min_tier_count,
        "max_heading_tier": max_heading_tier,
        "bpe_max_node_words": bpe_max_node_words,
        "bpe_level_pollution_ratio": bpe_level_pollution_ratio,
        "margin_band_ratio": margin_band_ratio,
        "margin_min_consecutive_pages": margin_min_consecutive_pages,
        "max_words": max_words,
        "max_words_coverage": max_words_coverage,
    }
    try:
        resolved = resolve_processing_config(
            config_path,
            cli_overrides=_legacy_process_cli_overrides(context, legacy_values),
            set_overrides=set_option,
        )
    except ConfigError as error:
        _exit_stage_input_error(
            "process",
            error,
            code="invalid_config",
            output_format=resolved_output_format,
        )

    if flat_output:
        _validate_flat_input_pdf(
            "process",
            pdf,
            output_format=resolved_output_format,
        )
        try:
            result = Processor(pdf, output_dir, resolved.config).run()
        except Exception as error:
            _exit_stage_runtime_error(
                "process",
                error,
                output_format=resolved_output_format,
                debug=debug,
            )
        _emit_stage_result(
            "process",
            result,
            result,
            output_format=resolved_output_format,
        )
        return

    try:
        run = create_run_context(
            pdf,
            output_dir,
            resolved,
            repository_root=Path.cwd(),
        )
    except RunError as error:
        _exit_stage_input_error(
            "process",
            error,
            code="invalid_input",
            output_format=resolved_output_format,
        )
    run.start()
    try:
        result = Processor(pdf, run.run_dir, resolved.config).run()
        manifest = run.complete(result)
    except Exception as error:
        run.fail(error)
        _exit_stage_runtime_error(
            "process",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    payload = {
        "run_id": manifest.run_id,
        "run_dir": manifest.run_dir,
        "manifest_path": run.manifest_path,
        "config_hash": manifest.config_hash,
        "result": result,
    }
    _emit_stage_result(
        "process",
        payload,
        result,
        output_format=resolved_output_format,
    )


def _run_infer(
    pdf: Path, output_dir: Path, config: ProcessingConfig
) -> ProcessingResult:
    """existing-outline policy를 따르고, 필요할 때만 typography 추론을 실행한다."""

    output_dir.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf) as document:
        total_pages = document.page_count

    decision = resolve_existing_outline_action(pdf, total_pages, config)
    if decision.reuse_existing:
        plan = outline_to_plan(decision.existing_outline)
        validation = validate_bookmark_plan(plan, total_pages)
        artifacts: dict[str, Path] = {}
        if config.write_artifacts:
            artifacts["existing_outline_plan"] = write_artifact(
                output_dir, "existing_outline_plan", plan
            )
            artifacts["bookmark_plan_validation"] = write_artifact(
                output_dir, "bookmark_plan_validation", validation
            )
            if decision.quality is not None:
                artifacts["existing_outline_quality"] = write_artifact(
                    output_dir, "existing_outline_quality", decision.quality
                )
        warnings = [
            f"기존 outline {len(plan)}개를 재사용했고 typography 추론은 실행하지 않았다."
        ] + validation.warnings
        if decision.quality is not None and decision.quality.is_low_quality:
            warnings.append(
                "기존 outline이 low quality로 판정됐다: "
                f"reasons={decision.quality.reasons}. "
                "outline_quality.replace_when_low_quality=true로 재추론할 수 있다."
            )
        result = ProcessingResult(
            status="skipped",
            input_pdf=pdf,
            bookmark_count=len(plan),
            confidence_summary=ConfidenceSummary(outline=1.0),
            warnings=warnings,
            artifact_paths=artifacts,
            existing_outline_quality=decision.quality,
        )
    else:
        analysis = analyze_pdf(pdf, config.typography)
        inference = infer_bookmarks(analysis, config.typography)
        artifacts = (
            write_inference_artifacts(output_dir, inference, decision.quality)
            if config.write_artifacts
            else {}
        )
        warnings = list(inference.validation.warnings)
        if decision.quality is not None and decision.quality.is_low_quality:
            warnings.append(
                "기존 outline이 low quality로 판정돼 typography 추론 결과로 "
                f"교체했다: reasons={decision.quality.reasons}"
            )
        result = ProcessingResult(
            status="processed" if inference.validation.valid else "failed",
            input_pdf=pdf,
            bookmark_count=len(inference.plan),
            confidence_summary=confidence_summary_for_inference(inference),
            warnings=warnings,
            artifact_paths=artifacts,
            existing_outline_quality=decision.quality,
        )
    report_path = write_processing_report(result, output_dir)
    return dataclass_replace(result, report_path=report_path)


@app.command()
def infer(
    pdf: Path = typer.Argument(..., help="추론할 PDF 파일이다."),
    output_dir: Path = typer.Option(
        Path("."), "--output-dir", "-o", help="run directory를 만들 output root다."
    ),
    config_path: Path | None = typer.Option(
        None, "--config", help="읽을 versioned TOML processing config다."
    ),
    set_option: list[str] = typer.Option(
        [],
        "--set",
        help="최종 config override다. dotted.key=value 형식으로 여러 번 줄 수 있다.",
    ),
    flat_output: bool = typer.Option(
        False,
        "--flat-output",
        help="호환을 위해 immutable run directory 없이 기존 flat output을 사용한다.",
    ),
    output_format: str = typer.Option(
        "human", "--format", help="final result 출력 형식이다: human, json."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """typography 추론으로 bookmark plan과 근거 artifact만 만든다.

    기존 outline이 있고 low quality가 아니면 outline_quality 정책에 따라
    추론을 건너뛴다. bookmarked PDF와 Markdown은 만들지 않는다 - 최종
    산출물이 필요하면 이 명령이 만든 plan을 ``apply``에 전달한다.
    """

    resolved_output_format = _stage_output_format(output_format)
    try:
        resolved = resolve_processing_config(config_path, set_overrides=set_option)
    except ConfigError as error:
        _exit_stage_input_error(
            "infer",
            error,
            code="invalid_config",
            output_format=resolved_output_format,
        )

    if flat_output:
        _validate_flat_input_pdf(
            "infer",
            pdf,
            output_format=resolved_output_format,
        )
        try:
            result = _run_infer(pdf, output_dir, resolved.config)
        except Exception as error:
            _exit_stage_runtime_error(
                "infer",
                error,
                output_format=resolved_output_format,
                debug=debug,
            )
        _emit_stage_result(
            "infer",
            result,
            result,
            output_format=resolved_output_format,
        )
        return

    try:
        run = create_run_context(pdf, output_dir, resolved, repository_root=Path.cwd())
    except RunError as error:
        _exit_stage_input_error(
            "infer",
            error,
            code="invalid_input",
            output_format=resolved_output_format,
        )
    run.start()
    try:
        result = _run_infer(pdf, run.run_dir, resolved.config)
        manifest = run.complete(result)
    except Exception as error:
        run.fail(error)
        _exit_stage_runtime_error(
            "infer",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    payload = {
        "run_id": manifest.run_id,
        "run_dir": manifest.run_dir,
        "manifest_path": run.manifest_path,
        "config_hash": manifest.config_hash,
        "result": result,
    }
    _emit_stage_result(
        "infer",
        payload,
        result,
        output_format=resolved_output_format,
    )


def _run_apply(
    pdf: Path,
    output_dir: Path,
    plan: list[BookmarkPlanItem],
    config: ProcessingConfig,
) -> ProcessingResult:
    """검증된 plan으로 bookmarked PDF/Markdown만 만든다. typography 추론은 하지 않는다."""

    output_dir.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf) as document:
        total_pages = document.page_count
    apply_result = apply_plan(pdf, output_dir, plan, total_pages, config.markdown_split)
    artifacts: dict[str, Path] = {}
    if config.write_artifacts:
        artifacts["bookmark_plan_validation"] = write_artifact(
            output_dir, "bookmark_plan_validation", apply_result.validation
        )
    result = ProcessingResult(
        status="processed" if apply_result.validation.valid else "failed",
        input_pdf=pdf,
        output_pdf=apply_result.output_pdf,
        output_markdown_dir=apply_result.output_markdown_dir,
        markdown_export=apply_result.markdown_export,
        bookmark_count=len(plan),
        confidence_summary=ConfidenceSummary(outline=1.0),
        warnings=list(apply_result.validation.warnings),
        artifact_paths=artifacts,
    )
    report_path = write_processing_report(result, output_dir)
    return dataclass_replace(result, report_path=report_path)


@app.command()
def apply(
    pdf: Path = typer.Argument(..., help="적용할 PDF 파일이다."),
    plan_path: Path = typer.Option(
        ..., "--plan", help="적용할 bookmark plan JSON 경로다."
    ),
    output_dir: Path = typer.Option(
        Path("."), "--output-dir", "-o", help="run directory를 만들 output root다."
    ),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        help="읽을 versioned TOML processing config다. markdown split 설정에만 쓰인다.",
    ),
    set_option: list[str] = typer.Option(
        [],
        "--set",
        help="최종 config override다. dotted.key=value 형식으로 여러 번 줄 수 있다.",
    ),
    flat_output: bool = typer.Option(
        False,
        "--flat-output",
        help="호환을 위해 immutable run directory 없이 기존 flat output을 사용한다.",
    ),
    output_format: str = typer.Option(
        "human", "--format", help="final result 출력 형식이다: human, json."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """검증된 bookmark plan을 읽어 최종 PDF/Markdown만 만든다.

    typography extraction과 inference는 다시 실행하지 않는다.
    """

    resolved_output_format = _stage_output_format(output_format)
    try:
        resolved = resolve_processing_config(config_path, set_overrides=set_option)
    except ConfigError as error:
        _exit_stage_input_error(
            "apply",
            error,
            code="invalid_config",
            output_format=resolved_output_format,
        )

    try:
        plan = load_bookmark_plan_json(plan_path)
    except PlanError as error:
        _exit_stage_input_error(
            "apply",
            error,
            code="invalid_plan",
            output_format=resolved_output_format,
        )

    if flat_output:
        _validate_flat_input_pdf(
            "apply",
            pdf,
            output_format=resolved_output_format,
        )
        try:
            result = _run_apply(pdf, output_dir, plan, resolved.config)
        except Exception as error:
            _exit_stage_runtime_error(
                "apply",
                error,
                output_format=resolved_output_format,
                debug=debug,
            )
        _emit_stage_result(
            "apply",
            result,
            result,
            output_format=resolved_output_format,
        )
        return

    try:
        run = create_run_context(pdf, output_dir, resolved, repository_root=Path.cwd())
    except RunError as error:
        _exit_stage_input_error(
            "apply",
            error,
            code="invalid_input",
            output_format=resolved_output_format,
        )
    run.start()
    try:
        result = _run_apply(pdf, run.run_dir, plan, resolved.config)
        run.record_plan_source(plan_path, file_sha256(plan_path))
        manifest = run.complete(result)
    except Exception as error:
        run.fail(error)
        _exit_stage_runtime_error(
            "apply",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    payload = {
        "run_id": manifest.run_id,
        "run_dir": manifest.run_dir,
        "manifest_path": run.manifest_path,
        "config_hash": manifest.config_hash,
        "result": result,
    }
    _emit_stage_result(
        "apply",
        payload,
        result,
        output_format=resolved_output_format,
    )


@app.command()
def batch(
    input_dir: Path = typer.Argument(..., help="PDF를 찾을 입력 디렉터리다."),
    output_dir: Path = typer.Option(
        Path("."), "--output-dir", "-o", help="출력 디렉터리다."
    ),
    recursive: bool = typer.Option(
        False, "--recursive", "-r", help="하위 디렉터리까지 찾는다."
    ),
) -> None:
    """디렉터리 안의 PDF들을 batch 처리한다."""

    result = BatchProcessor(input_dir, output_dir, recursive=recursive).run()
    rich_print(to_jsonable(result))


@app.command("classify-scan")
def classify_scan_cmd(
    input_dir: Path = typer.Argument(..., help="PDF를 찾을 입력 디렉터리다."),
    output_dir: Path = typer.Option(
        Path("."), "--output-dir", "-o", help="분류 report를 저장할 디렉터리다."
    ),
    recursive: bool = typer.Option(
        False, "--recursive", "-r", help="하위 디렉터리까지 찾는다."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="후속 변경 작업 없이 scan/bookmark 분류만 실행한다.",
    ),
    write_report: bool = typer.Option(
        True,
        "--write-report/--no-write-report",
        help="분류 CSV/JSONL/summary report를 저장할지 정한다.",
    ),
    max_sample_pages: int = typer.Option(
        DEFAULT_MAX_SAMPLE_PAGES,
        "--max-sample-pages",
        min=1,
        help="문서당 sampling할 최대 page 수다.",
    ),
    log_mode: str = typer.Option(
        "auto",
        "--log-mode",
        help="classify 진행 로그 출력 방식이다. auto, rich, plain, json, none 중 하나다.",
    ),
    output_format: str = typer.Option(
        "human", "--format", help="최종 결과 출력 형식이다: human, json."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """디렉터리 안 PDF를 scan 여부와 bookmark 유무로 분류해 report를 만든다."""

    command = "classify-scan"
    resolved_output_format = _stage_output_format(output_format)
    resolved_log_mode = default_classify_log_mode() if log_mode == "auto" else log_mode
    if resolved_log_mode not in {"rich", "plain", "json", "none"}:
        _exit_stage_input_error(
            command,
            ValueError("log-mode은 auto, rich, plain, json, none 중 하나여야 한다."),
            code="invalid_input",
            output_format=resolved_output_format,
        )
    if not input_dir.is_dir():
        _exit_stage_input_error(
            command,
            FileNotFoundError(f"입력 디렉터리가 없다: {input_dir.resolve()}"),
            code="invalid_input",
            output_format=resolved_output_format,
        )
    try:
        logger = build_classify_logger(cast(ClassifyLogMode, resolved_log_mode))
        config = ClassifyBatchConfig(
            input_dir=input_dir,
            output_dir=output_dir,
            recursive=recursive,
            dry_run=dry_run,
            write_report=write_report,
            max_sample_pages=max_sample_pages,
        )
        result = ScanBookmarkClassifier(config, logger=logger).run()
    except (
        FileExistsError,
        FileNotFoundError,
        NotADirectoryError,
        ValueError,
    ) as error:
        _exit_stage_input_error(
            command,
            error,
            code="invalid_input",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            command,
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    payload = {
        "total_pdf_count": result.total_pdf_count,
        "scanned_count": result.scanned_count,
        "native_count": result.native_count,
        "target_count": result.target_count,
        "error_count": result.error_count,
        "elapsed_sec": result.elapsed_sec,
        "dry_run": dry_run,
        "write_report": write_report,
        "report_csv_path": result.report_csv_path,
        "detail_jsonl_path": result.detail_jsonl_path,
    }
    emit_command_result(command, payload, output_format=resolved_output_format)


def main() -> None:
    """콘솔 script entrypoint다."""

    app()
