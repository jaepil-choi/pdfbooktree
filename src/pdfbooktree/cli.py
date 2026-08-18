"""Typer 기반 CLI entrypoint다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import fitz
import typer

from pdfbooktree._version import package_version
from pdfbooktree.batch import BatchProcessor
from pdfbooktree.batch_logger import (
    BatchLogMode,
    build_batch_logger,
    default_batch_log_mode,
)
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
    inspect_compare_markdown,
    inspect_compare_plans,
    inspect_heading_sweep,
    inspect_markdown_tree,
    inspect_ocr_artifact,
    inspect_page_count,
    inspect_plan_artifact,
    inspect_text,
)
from pdfbooktree.models import BookmarkPlanItem, ProcessingResult
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
from pdfbooktree.optional_dependencies import (
    OptionalDependencyError,
    require_ocr_dependencies,
)
from pdfbooktree.pdf.scan_signals import DEFAULT_MAX_SAMPLE_PAGES
from pdfbooktree.processing_logger import (
    ProcessingLogger,
    ProcessingLogMode,
    build_processing_logger,
    default_processing_log_mode,
)
from pdfbooktree.processor import Processor
from pdfbooktree.project_skill import (
    SkillInstallError,
    install_project_skill,
    uninstall_project_skill,
)
from pdfbooktree.run import RunError
from pdfbooktree.workflows import (
    apply_plan_to_directory,
    apply_plan_file,
    infer_to_directory,
    infer_pdf,
    preview_apply_plan,
    process_pdf,
)

app = typer.Typer(
    help="PDF 책의 typography hierarchy로 bookmark와 Markdown tree를 만든다.",
    no_args_is_help=True,
    rich_markup_mode=None,
)
inspect_app = typer.Typer(
    help="PDF와 처리 artifact를 읽기 전용으로 조사한다.",
    rich_markup_mode=None,
)
config_app = typer.Typer(
    help="versioned processing config를 생성하고 검증한다.",
    rich_markup_mode=None,
)
skill_app = typer.Typer(
    help="pdfbooktree 사용 skill을 project scope에 설치한다.",
    rich_markup_mode=None,
)
app.add_typer(inspect_app, name="inspect")
app.add_typer(config_app, name="config")
app.add_typer(skill_app, name="skill")


def _version_callback(value: bool) -> None:
    """설치된 package version을 출력하고 즉시 종료한다."""

    if not value:
        return
    typer.echo(f"pdfbooktree {package_version()}")
    raise typer.Exit()


@app.callback()
def root_callback(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="설치된 pdfbooktree version을 출력한다.",
    ),
) -> None:
    """pdfbooktree 최상위 option을 처리한다."""


def _stage_output_format(value: str) -> OutputFormat:
    """단계형 command의 출력 형식을 Typer 입력 오류로 검증한다."""

    try:
        return parse_output_format(value)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def _build_stage_processing_logger(
    command: str,
    log_mode: str,
    *,
    output_format: OutputFormat,
) -> ProcessingLogger:
    """process/infer log mode를 검증하고 stderr logger를 만든다."""

    resolved = default_processing_log_mode() if log_mode == "auto" else log_mode
    if resolved not in {"rich", "plain", "json", "none"}:
        _exit_stage_input_error(
            command,
            ValueError("log-mode은 auto, rich, plain, json, none 중 하나여야 한다."),
            code="invalid_input",
            output_format=output_format,
        )
    return build_processing_logger(cast(ProcessingLogMode, resolved), command=command)


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
    code: str = "runtime_error",
) -> None:
    """예상하지 못한 runtime 오류를 숨기거나 debug에서 다시 발생시킨다."""

    if debug:
        raise error
    resolved_code = (
        "missing_optional_dependency"
        if isinstance(error, OptionalDependencyError)
        else code
    )
    exit_command_error(
        command,
        error,
        code=resolved_code,
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


@skill_app.command("install")
def skill_install_cmd(
    project_dir: Path = typer.Option(
        Path("."),
        "--project-dir",
        "-p",
        help=".agents/skills를 만들 project root다. 기본값은 현재 directory다.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="기존 use-pdfbooktree skill directory 전체를 교체한다.",
    ),
    output_format: str = typer.Option(
        "human", "--format", help="출력 형식이다: human, json."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """현재 또는 지정한 project에 use-pdfbooktree skill을 설치한다."""

    command = "skill.install"
    resolved_output_format = _stage_output_format(output_format)
    try:
        result = install_project_skill(project_dir, force=force)
    except SkillInstallError as error:
        _exit_stage_input_error(
            command,
            error,
            code="skill_install_error",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            command,
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    emit_command_result(command, result, output_format=resolved_output_format)


@skill_app.command("uninstall")
def skill_uninstall_cmd(
    project_dir: Path = typer.Option(
        Path("."),
        "--project-dir",
        "-p",
        help="skill을 제거할 project root다. 기본값은 현재 directory다.",
    ),
    output_format: str = typer.Option(
        "human", "--format", help="출력 형식이다: human, json."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """``skill install``이 만든 것만 정확히 찾아 제거한다."""

    command = "skill.uninstall"
    resolved_output_format = _stage_output_format(output_format)
    try:
        result = uninstall_project_skill(project_dir)
    except SkillInstallError as error:
        _exit_stage_input_error(
            command,
            error,
            code="skill_uninstall_error",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            command,
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    emit_command_result(command, result, output_format=resolved_output_format)


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


def parse_closed_page_range(value: str | None) -> tuple[int, int] | None:
    """inspect plan의 단일 1-based page 또는 닫힌 범위를 해석한다."""

    if value is None or not value.strip():
        return None
    token = value.strip()
    if "," in token:
        raise typer.BadParameter("--page-range는 단일 page 또는 start-end 형식이다.")
    try:
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text)
            end = int(end_text)
        else:
            start = end = int(token)
    except ValueError as exc:
        raise typer.BadParameter(
            "--page-range는 단일 page 또는 start-end 정수 형식이어야 한다."
        ) from exc
    if start < 1 or end < start:
        raise typer.BadParameter("--page-range는 1 이상의 오름차순 범위여야 한다.")
    return start, end


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


def _parse_positive_int_list(value: str, option: str) -> list[int]:
    """comma로 구분한 1 이상 정수 목록을 파싱한다."""

    values: list[int] = []
    for part in value.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            parsed = int(token)
        except ValueError as exc:
            raise typer.BadParameter(f"{option}은 정수 목록이어야 한다.") from exc
        if parsed < 1:
            raise typer.BadParameter(f"{option}의 모든 값은 1 이상이어야 한다.")
        values.append(parsed)
    if not values:
        raise typer.BadParameter(f"{option}은 하나 이상의 값을 가져야 한다.")
    return values


@inspect_app.command("sweep")
def inspect_sweep_cmd(
    pdf: Path = typer.Argument(..., help="확인할 PDF 파일이다."),
    size_class_depths: str = typer.Option(
        "1,2,3",
        "--size-class-depths",
        help="sweep할 typography.size_class_depth 값 목록이다. 예: 1,2,3",
    ),
    max_headings_per_page_values: str = typer.Option(
        "1,2,3,5,8,999",
        "--max-headings-per-page",
        help="sweep할 typography.max_headings_per_page 값 목록이다. 예: 1,2,3,5,8,999",
    ),
    min_word_counts: str = typer.Option(
        "1,2",
        "--min-words",
        help="sweep할 heading 후보 최소 단어 수 목록이다. 예: 1,2",
    ),
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
    """typography를 한 번만 분석하고 heading knob 조합을 메모리에서 sweep한다.

    ``process``를 설정마다 반복 실행하지 않고, candidate 수와 page당 candidate
    분포로 다음에 조절할 knob 방향을 고를 수 있게 한다. output artifact는
    만들지 않는다.
    """

    resolved_output_format = _inspection_output_format(output_format, as_json=as_json)
    try:
        result = inspect_heading_sweep(
            pdf,
            size_class_depths=_parse_positive_int_list(
                size_class_depths, "--size-class-depths"
            ),
            max_headings_per_page_values=_parse_positive_int_list(
                max_headings_per_page_values, "--max-headings-per-page"
            ),
            min_word_counts=_parse_positive_int_list(min_word_counts, "--min-words"),
        )
    except (FileNotFoundError, ValueError, typer.BadParameter) as error:
        _exit_stage_input_error(
            "inspect.sweep",
            error,
            code="invalid_input",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            "inspect.sweep",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    if resolved_output_format == "human":
        result = _render_heading_sweep_human(result)
    emit_command_result("inspect.sweep", result, output_format=resolved_output_format)


def _render_heading_sweep_human(result: dict[str, Any]) -> str:
    """setting별 candidate 수와 knob 방향이 한눈에 보이는 human 요약을 만든다."""

    summary = result["summary"]
    lines = [
        f"pdf: {result['pdf_path']}",
        f"page_count: {result['page_count']}, body_line_count: {result['body_line_count']}",
        f"settings_tried: {result['settings_tried']} (typography 분석은 1회만 수행)",
        (
            "sensible_pages_per_candidate_range: "
            f"{summary['sensible_pages_per_candidate_range']}"
        ),
        f"plausible_setting_count: {summary['plausible_setting_count']}",
    ]
    if summary["plausible_settings"]:
        lines.append("plausible_settings:")
        for setting in summary["plausible_settings"]:
            lines.append(
                "  - depth={size_class_depth} max_per_page={max_headings_per_page} "
                "min_words={min_words} -> candidates={candidate_count}, "
                "pages_with_candidate={pages_with_candidate_count}, "
                "pages_per_candidate={pages_per_candidate}".format(**setting)
            )
    else:
        lines.append("plausible_settings: 없음")
    lines.append(
        "knob direction: size_class_depth={}, max_headings_per_page={}, "
        "min_words={}".format(
            summary["size_class_depth_direction"],
            summary["max_headings_per_page_direction"],
            summary["min_words_direction"],
        )
    )
    lines.append("settings:")
    for setting in result["settings"]:
        lines.append(
            "  - depth={size_class_depth} max_per_page={max_headings_per_page} "
            "min_words={min_words} -> candidates={candidate_count}, "
            "pages_with_candidate={pages_with_candidate_count}, "
            "pages_per_candidate={pages_per_candidate}".format(**setting)
        )
    return "\n".join(lines)


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
    summary: bool = typer.Option(
        False,
        "--summary",
        help="review summary와 기존 plan/Markdown 요약만 반환한다.",
    ),
    items: bool = typer.Option(
        False,
        "--items",
        help="bookmark review item을 반환한다.",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        min=1,
        max=1000,
        help="반환할 review item 최대 개수다.",
    ),
    item_id: str | None = typer.Option(
        None,
        "--item-id",
        help="단일 plan node ID를 확인한다. 예: n0042.",
    ),
    page_range: str | None = typer.Option(
        None,
        "--page-range",
        help="1-based PDF page 범위다. 예: 100-120.",
    ),
    level: int | None = typer.Option(
        None,
        "--level",
        min=1,
        help="bookmark level로 review item을 제한한다.",
    ),
    source: str | None = typer.Option(
        None,
        "--source",
        help="bookmark source로 review item을 제한한다.",
    ),
    attention_only: bool = typer.Option(
        False,
        "--attention-only",
        help="attention signal이 있는 review item만 반환한다.",
    ),
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
    """bookmark plan summary에서 item 근거까지 점진적으로 확인한다."""

    resolved_output_format = _inspection_output_format(output_format, as_json=as_json)
    try:
        query_requested = any(
            (
                items,
                item_id is not None,
                page_range is not None,
                level is not None,
                source is not None,
                attention_only,
            )
        )
        if summary and query_requested:
            raise typer.BadParameter(
                "--summary는 item selector/filter와 함께 사용할 수 없다."
            )
        parsed_page_range = parse_closed_page_range(page_range)
        result = inspect_plan_artifact(
            output_dir,
            include_items=query_requested,
            limit=limit,
            item_id=item_id,
            page_range=parsed_page_range,
            level=level,
            source=source,
            attention_only=attention_only,
        )
    except (FileNotFoundError, ValueError, typer.BadParameter) as error:
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


@inspect_app.command("markdown")
def inspect_markdown_cmd(
    target: Path = typer.Argument(
        ...,
        help="process output directory 또는 markdown_manifest.json 경로다.",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        min=1,
        max=1000,
        help="title fragment sample 최대 개수다.",
    ),
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
    """Markdown tree manifest의 verdict, finding, 재시도 후보를 확인한다."""

    resolved_output_format = _inspection_output_format(output_format, as_json=as_json)
    try:
        result = inspect_markdown_tree(target, limit=limit)
    except (FileNotFoundError, ValueError) as error:
        _exit_stage_input_error(
            "inspect.markdown",
            error,
            code="invalid_input",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            "inspect.markdown",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    if resolved_output_format == "human":
        result = _render_markdown_tree_human(result)
    emit_command_result(
        "inspect.markdown", result, output_format=resolved_output_format
    )


def _render_markdown_tree_human(result: dict[str, Any]) -> str:
    """verdict, finding, 재시도 command가 한눈에 보이는 human 요약을 만든다."""

    lines = [
        f"verdict: {result['verdict']}",
        f"manifest: {result['manifest_path']}",
        (
            f"graph: export_mode={result['graph']['export_mode']}, "
            f"node_count={result['graph']['node_count']}, "
            f"chosen_level={result['graph']['chosen_level']}"
        ),
        (
            f"coverage: unassigned_ratio={result['coverage']['unassigned_ratio']}, "
            f"duplicated_page_count={result['coverage']['duplicated_page_count']}"
        ),
        f"titles: fragment_ratio={result['titles']['fragment_ratio']}",
    ]
    if not result["findings"]:
        lines.append("findings: 없음")
    else:
        lines.append("findings:")
        for finding in result["findings"]:
            lines.append(
                f"  - [{finding['severity']}] {finding['code']} "
                f"(cause={finding['cause']}): {finding['detail']}"
            )
    if not result["retry"]:
        lines.append("retry: 없음")
    else:
        lines.append("retry:")
        for candidate in result["retry"]:
            lines.append(f"  - cause={candidate['cause']}")
            lines.append(f"    command: {candidate['command']}")
            lines.append(f"    reason: {candidate['reason']}")
    if result["warnings"]:
        lines.append("warnings:")
        for warning in result["warnings"]:
            lines.append(f"  - {warning}")
    return "\n".join(lines)


@inspect_app.command("compare")
def inspect_compare_cmd(
    plan_a: Path = typer.Argument(
        ..., help="비교 기준(before) bookmark plan JSON 또는 markdown manifest다."
    ),
    plan_b: Path = typer.Argument(
        ..., help="비교 대상(after) bookmark plan JSON 또는 markdown manifest다."
    ),
    page_tolerance: int = typer.Option(
        0,
        "--page-tolerance",
        min=0,
        help="같은 항목으로 볼 page 오차 허용치다. plan 비교에만 적용한다.",
    ),
    title_similarity_threshold: float = typer.Option(
        0.7,
        "--title-similarity-threshold",
        min=0.0,
        max=1.0,
        help="같은 항목으로 볼 title 유사도 최소값이다. plan 비교에만 적용한다.",
    ),
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
    """두 JSON을 자동 판별해 bookmark plan diff 또는 Markdown manifest 비교를 한다."""

    resolved_output_format = _inspection_output_format(output_format, as_json=as_json)
    try:
        value_a = _read_compare_input(plan_a)
        value_b = _read_compare_input(plan_b)
        is_a_markdown = _is_markdown_manifest_value(value_a)
        is_b_markdown = _is_markdown_manifest_value(value_b)
        if is_a_markdown or is_b_markdown:
            if not (is_a_markdown and is_b_markdown):
                raise ValueError(
                    "한쪽만 Markdown manifest(nodes 포함)다: "
                    f"plan_a={plan_a}, plan_b={plan_b}"
                )
            result = inspect_compare_markdown(plan_a, plan_b)
        else:
            result = inspect_compare_plans(
                plan_a,
                plan_b,
                page_tolerance=page_tolerance,
                title_similarity_threshold=title_similarity_threshold,
            )
    except (FileNotFoundError, ValueError) as error:
        _exit_stage_input_error(
            "inspect.compare",
            error,
            code="invalid_input",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            "inspect.compare",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    emit_command_result("inspect.compare", result, output_format=resolved_output_format)


def _read_compare_input(path: Path) -> object:
    """compare dispatch가 판별에 쓸 raw JSON 값을 파일당 정확히 한 번 읽는다.

    이 값은 markdown/plan 판별에만 쓰고, 실제 비교는
    ``inspect_compare_markdown()``/``inspect_compare_plans()``가 각자의 loader로
    다시 읽는다. 손상된 JSON은 여기서 바로 input 오류로 보고하고, plan 경로로
    조용히 넘어가 다른 오류 메시지를 내지 않는다.
    """

    if not path.is_file():
        raise FileNotFoundError(f"비교 입력 파일이 없다: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(
            f"비교 입력 파일을 읽지 못했다: path={path}, reason={error}"
        ) from error
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"비교 입력 파일이 유효한 JSON이 아니다: path={path}, reason={error}"
        ) from error


def _is_markdown_manifest_value(value: object) -> bool:
    """markdown manifest 판별 predicate다.

    ``_load_markdown_manifest_for_compare()``가 실제로 강제하는 조건(nodes
    유무)과 정확히 같은 조건을 써서, 판별과 실제 loader가 서로 다른 파일을
    다르게 분류하지 않게 한다.
    """

    return isinstance(value, dict) and "nodes" in value


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
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="OCR cache와 stats artifact 디렉터리다. 기본값은 <output-stem>_artifacts다.",
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
        require_ocr_dependencies()
        resolved_ocr_output_dir = output_dir or (
            output_pdf.parent / f"{output_pdf.stem}_artifacts"
        )
        logger = build_ocr_logger(
            cast(OcrLogMode, resolved_log_mode),
            resolved_ocr_output_dir,
            enable_file=not no_log_file,
            desc=f"OCR overlay: {pdf.name}",
        )
        config = OcrOverlayConfig(
            input_pdf=pdf,
            output_pdf=output_pdf,
            output_dir=resolved_ocr_output_dir,
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
    include_glob: list[str] = typer.Option(
        [],
        "--include-glob",
        help="포함할 상대 POSIX 경로 glob이다. 여러 번 지정할 수 있다.",
    ),
    exclude_glob: list[str] = typer.Option(
        [],
        "--exclude-glob",
        help="제외할 상대 POSIX 경로 glob이다. include보다 우선한다.",
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
    min_page_count: int = typer.Option(
        1,
        "--min-page-count",
        min=1,
        help="OCR 대상에 포함할 최소 PDF page 수다. 지정값 이상만 처리한다.",
    ),
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
    output_format: str = typer.Option(
        "human", "--format", help="최종 결과 출력 형식이다: human, json."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """디렉터리 안 target PDF만 골라 OCR overlay를 batch 실행한다."""

    command = "ocr-overlay-batch"
    resolved_output_format = _stage_output_format(output_format)
    resolved_log_mode = default_ocr_log_mode() if log_mode == "auto" else log_mode
    if resolved_log_mode not in {"tqdm", "plain", "json", "none"}:
        _exit_stage_input_error(
            command,
            ValueError("log-mode은 auto, tqdm, plain, json, none 중 하나여야 한다."),
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
            min_page_count=min_page_count,
            max_sample_pages=max_sample_pages,
            stats_word_level=stats_word_level,
            include_globs=tuple(include_glob),
            exclude_globs=tuple(exclude_glob),
        )
        runner = OcrOverlayBatchRunner(
            config,
            log_mode=cast(OcrLogMode, resolved_log_mode),
            enable_log_file=not no_log_file,
        )
        result = runner.run()
    except (
        FileExistsError,
        FileNotFoundError,
        NotADirectoryError,
        ValueError,
        typer.BadParameter,
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
        "target_count": result.target_count,
        "target_page_count": result.target_page_count,
        "will_process_count": result.will_process_count,
        "will_process_page_count": result.will_process_page_count,
        "processed_count": result.processed_count,
        "dry_run_count": result.dry_run_count,
        "skipped_count": result.skipped_count,
        "failed_count": result.failed_count,
        "mupdf_warning_pdf_count": result.mupdf_warning_pdf_count,
        "mupdf_warning_count": result.mupdf_warning_count,
        "elapsed_sec": result.elapsed_sec,
        "report_csv_path": result.report_csv_path,
        "detail_jsonl_path": result.detail_jsonl_path,
        "summary_path": result.summary_path,
        "include_globs": result.include_globs,
        "exclude_globs": result.exclude_globs,
        "excluded_output_subtree": result.excluded_output_subtree,
    }
    emit_command_result(command, payload, output_format=resolved_output_format)


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
    in_place: bool = typer.Option(
        False,
        "--in-place",
        help="별도 bookmarked PDF를 만들지 않고 입력 PDF를 atomic 교체한다.",
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
    log_mode: str = typer.Option(
        "auto",
        "--log-mode",
        help="처리 진행 로그 방식이다. auto, rich, plain, json, none 중 하나다.",
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
        logger = _build_stage_processing_logger(
            "process", log_mode, output_format=resolved_output_format
        )
        try:
            processor_kwargs = {"in_place": True} if in_place else {}
            result = Processor(
                pdf,
                output_dir,
                resolved.config,
                log=logger,
                **processor_kwargs,
            ).run()
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

    logger = _build_stage_processing_logger(
        "process", log_mode, output_format=resolved_output_format
    )
    try:
        workflow = process_pdf(
            pdf,
            output_dir,
            resolved,
            log=logger,
            in_place=in_place,
        )
    except RunError as error:
        _exit_stage_input_error(
            "process",
            error,
            code="invalid_input",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            "process",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    payload = {
        "run_id": workflow.run_id,
        "run_dir": workflow.run_dir,
        "manifest_path": workflow.manifest_path,
        "config_hash": workflow.config_hash,
        "result": workflow.result,
    }
    _emit_stage_result(
        "process",
        payload,
        workflow.result,
        output_format=resolved_output_format,
    )


def _run_infer(
    pdf: Path,
    output_dir: Path,
    config: ProcessingConfig,
    log: ProcessingLogger | None = None,
) -> ProcessingResult:
    """existing-outline policy를 따르고, 필요할 때만 typography 추론을 실행한다."""

    return infer_to_directory(pdf, output_dir, config, log)


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
    log_mode: str = typer.Option(
        "auto",
        "--log-mode",
        help="추론 진행 로그 방식이다. auto, rich, plain, json, none 중 하나다.",
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
        logger = _build_stage_processing_logger(
            "infer", log_mode, output_format=resolved_output_format
        )
        try:
            result = _run_infer(pdf, output_dir, resolved.config, logger)
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

    logger = _build_stage_processing_logger(
        "infer", log_mode, output_format=resolved_output_format
    )
    try:
        workflow = infer_pdf(pdf, output_dir, resolved, log=logger)
    except RunError as error:
        _exit_stage_input_error(
            "infer",
            error,
            code="invalid_input",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            "infer",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    payload = {
        "run_id": workflow.run_id,
        "run_dir": workflow.run_dir,
        "manifest_path": workflow.manifest_path,
        "config_hash": workflow.config_hash,
        "result": workflow.result,
    }
    _emit_stage_result(
        "infer",
        payload,
        workflow.result,
        output_format=resolved_output_format,
    )


def _run_apply(
    pdf: Path,
    output_dir: Path,
    plan: list[BookmarkPlanItem],
    config: ProcessingConfig,
    *,
    in_place: bool = False,
) -> ProcessingResult:
    """검증된 plan으로 bookmarked PDF/Markdown만 만든다. typography 추론은 하지 않는다."""

    return apply_plan_to_directory(
        pdf,
        output_dir,
        plan,
        config,
        in_place=in_place,
    )


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
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="plan과 PDF page 범위만 검증하고 run directory나 산출물을 만들지 않는다.",
    ),
    in_place: bool = typer.Option(
        False,
        "--in-place",
        help="별도 bookmarked PDF를 만들지 않고 입력 PDF를 atomic 교체한다.",
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

    if dry_run:
        try:
            preview = preview_apply_plan(
                pdf,
                plan_path,
                output_dir,
                resolved,
                in_place=in_place,
            )
        except (PlanError, RunError, FileNotFoundError) as error:
            _exit_stage_input_error(
                "apply",
                error,
                code="invalid_input",
                output_format=resolved_output_format,
            )
        payload = {
            "status": preview.status,
            "dry_run": preview.dry_run,
            "input_pdf": preview.input_pdf,
            "input_sha256": preview.input_sha256,
            "plan_path": preview.plan_path,
            "plan_sha256": preview.plan_sha256,
            "total_pages": preview.total_pages,
            "bookmark_count": preview.bookmark_count,
            "validation": preview.validation,
            "planned_output_pdf": preview.planned_output_pdf,
            "planned_output_markdown_dir": preview.planned_output_markdown_dir,
        }
        if not preview.validation.valid:
            exit_command_error(
                "apply",
                ProcessingFailedError("bookmark plan 구조 검증에 실패했다."),
                code="processing_failed",
                exit_code=CLI_EXIT_PROCESSING_FAILED,
                output_format=resolved_output_format,
                details=payload,
            )
        emit_command_result(
            "apply",
            payload,
            output_format=resolved_output_format,
        )
        return

    if flat_output:
        _validate_flat_input_pdf(
            "apply",
            pdf,
            output_format=resolved_output_format,
        )
        try:
            result = _run_apply(
                pdf,
                output_dir,
                plan,
                resolved.config,
                in_place=in_place,
            )
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
        workflow = apply_plan_file(
            pdf,
            plan_path,
            output_dir,
            resolved,
            in_place=in_place,
        )
    except (PlanError, RunError) as error:
        _exit_stage_input_error(
            "apply",
            error,
            code="invalid_input",
            output_format=resolved_output_format,
        )
    except Exception as error:
        _exit_stage_runtime_error(
            "apply",
            error,
            output_format=resolved_output_format,
            debug=debug,
        )
    payload = {
        "run_id": workflow.run_id,
        "run_dir": workflow.run_dir,
        "manifest_path": workflow.manifest_path,
        "config_hash": workflow.config_hash,
        "result": workflow.result,
    }
    _emit_stage_result(
        "apply",
        payload,
        workflow.result,
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
    include_glob: list[str] = typer.Option(
        [],
        "--include-glob",
        help="포함할 상대 POSIX 경로 glob이다. 여러 번 지정할 수 있다.",
    ),
    exclude_glob: list[str] = typer.Option(
        [],
        "--exclude-glob",
        help="제외할 상대 POSIX 경로 glob이다. include보다 우선한다.",
    ),
    config_path: Path | None = typer.Option(
        None, "--config", help="읽을 versioned TOML processing config다."
    ),
    set_option: list[str] = typer.Option(
        [],
        "--set",
        help="최종 config override다. dotted.key=value 형식으로 여러 번 줄 수 있다.",
    ),
    in_place: bool = typer.Option(
        False,
        "--in-place",
        help="각 입력 PDF를 검증된 temporary PDF로 atomic 교체한다.",
    ),
    log_mode: str = typer.Option(
        "auto",
        "--log-mode",
        help="batch 진행 로그 출력 방식이다. auto, rich, plain, json, none 중 하나다.",
    ),
    output_format: str = typer.Option(
        "human", "--format", help="최종 결과 출력 형식이다: human, json."
    ),
    debug: bool = typer.Option(
        False, "--debug", help="예상하지 못한 오류의 traceback을 그대로 노출한다."
    ),
) -> None:
    """디렉터리 안의 PDF들을 batch 처리한다."""

    command = "batch"
    resolved_output_format = _stage_output_format(output_format)
    resolved_log_mode = default_batch_log_mode() if log_mode == "auto" else log_mode
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
        resolved = resolve_processing_config(config_path, set_overrides=set_option)
    except ConfigError as error:
        _exit_stage_input_error(
            command,
            error,
            code="invalid_config",
            output_format=resolved_output_format,
        )
    try:
        batch_logger = build_batch_logger(cast(BatchLogMode, resolved_log_mode))
        batch_kwargs = {"in_place": True} if in_place else {}
        result = BatchProcessor(
            input_dir,
            output_dir,
            resolved,
            recursive=recursive,
            include_globs=tuple(include_glob),
            exclude_globs=tuple(exclude_glob),
            log=batch_logger,
            **batch_kwargs,
        ).run()
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
    emit_command_result(command, result, output_format=resolved_output_format)


@app.command("classify-scan")
def classify_scan_cmd(
    input_dir: Path = typer.Argument(..., help="PDF를 찾을 입력 디렉터리다."),
    output_dir: Path = typer.Option(
        Path("."), "--output-dir", "-o", help="분류 report를 저장할 디렉터리다."
    ),
    recursive: bool = typer.Option(
        False, "--recursive", "-r", help="하위 디렉터리까지 찾는다."
    ),
    include_glob: list[str] = typer.Option(
        [],
        "--include-glob",
        help="포함할 상대 POSIX 경로 glob이다. 여러 번 지정할 수 있다.",
    ),
    exclude_glob: list[str] = typer.Option(
        [],
        "--exclude-glob",
        help="제외할 상대 POSIX 경로 glob이다. include보다 우선한다.",
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
            include_globs=tuple(include_glob),
            exclude_globs=tuple(exclude_glob),
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
        "include_globs": result.include_globs,
        "exclude_globs": result.exclude_globs,
        "excluded_output_subtree": result.excluded_output_subtree,
    }
    emit_command_result(command, payload, output_format=resolved_output_format)


def main() -> None:
    """콘솔 script entrypoint다."""

    app()
