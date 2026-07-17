"""CLI final result와 error의 versioned 출력 계약이다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, NoReturn, cast

import typer
from rich import print as rich_print

from pdfbooktree.utils.jsonio import to_jsonable

CLI_RESULT_SCHEMA_VERSION = 1
CLI_EVENT_SCHEMA_VERSION = 1

CLI_EXIT_RUNTIME_ERROR = 1
CLI_EXIT_INPUT_ERROR = 2
CLI_EXIT_PROCESSING_FAILED = 3

OutputFormat = Literal["human", "json"]


class ProcessingFailedError(RuntimeError):
    """pipeline이 예외 없이 끝났지만 유효한 결과를 만들지 못했다."""


@dataclass(frozen=True)
class CommandError:
    """agent가 분기 가능한 command 오류다."""

    code: str
    type: str
    message: str
    details: Any | None = None


@dataclass(frozen=True)
class CommandResultEnvelope:
    """성공한 command의 final result envelope다."""

    schema_version: int
    command: str
    ok: Literal[True]
    result: Any


@dataclass(frozen=True)
class CommandErrorEnvelope:
    """실패한 command의 final error envelope다."""

    schema_version: int
    command: str
    ok: Literal[False]
    error: CommandError


@dataclass(frozen=True)
class CommandEventEnvelope:
    """실행 중 진행 상태를 stderr JSONL로 내보내는 event envelope다."""

    schema_version: int
    command: str
    event: str
    level: str
    message: str
    data: Any


def parse_output_format(value: str) -> OutputFormat:
    """문자열 출력 형식을 검증하고 좁은 타입으로 반환한다."""

    if value not in {"human", "json"}:
        raise ValueError("format은 human 또는 json이어야 한다.")
    return cast(OutputFormat, value)


def emit_command_result(
    command: str,
    result: object,
    *,
    output_format: OutputFormat,
) -> None:
    """성공 결과를 human 또는 JSON stdout으로 출력한다."""

    if output_format == "human":
        if isinstance(result, str):
            typer.echo(result)
        else:
            rich_print(to_jsonable(result))
        return
    envelope = CommandResultEnvelope(
        schema_version=CLI_RESULT_SCHEMA_VERSION,
        command=command,
        ok=True,
        result=result,
    )
    # JSON의 \u escape는 의미를 바꾸지 않으면서 CP949 같은 Windows terminal에서도
    # 모든 Unicode title을 안전하게 stdout으로 전달한다.
    typer.echo(json.dumps(to_jsonable(envelope), ensure_ascii=True))


def render_command_event_json(
    command: str,
    event: str,
    *,
    level: str,
    message: str,
    data: object,
) -> str:
    """진행 event 하나를 versioned JSONL 한 줄로 직렬화한다."""

    envelope = CommandEventEnvelope(
        schema_version=CLI_EVENT_SCHEMA_VERSION,
        command=command,
        event=event,
        level=level,
        message=message,
        data=data,
    )
    return json.dumps(to_jsonable(envelope), ensure_ascii=True)


def exit_command_error(
    command: str,
    error: Exception,
    *,
    code: str,
    exit_code: int,
    output_format: OutputFormat,
    details: object | None = None,
) -> NoReturn:
    """오류를 stderr에 출력하고 문서화된 exit code로 종료한다."""

    command_error = CommandError(
        code=code,
        type=type(error).__name__,
        message=str(error),
        details=details,
    )
    if output_format == "json":
        envelope = CommandErrorEnvelope(
            schema_version=CLI_RESULT_SCHEMA_VERSION,
            command=command,
            ok=False,
            error=command_error,
        )
        typer.echo(
            json.dumps(to_jsonable(envelope), ensure_ascii=True),
            err=True,
        )
    else:
        typer.echo(f"Error [{code}]: {error}", err=True)
    raise typer.Exit(code=exit_code)
