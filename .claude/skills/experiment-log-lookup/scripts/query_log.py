"""experiments/experiments.json, showcase/showcase.json 조회 도구.

전체 JSON을 읽지 않고도 원하는 experiment/showcase 항목만 골라 볼 수 있도록
list / get / search 세 가지 서브커맨드를 제공한다. 이 스크립트는 로그 파일을
읽기만 하며, 절대 experiments.json/showcase.json 내용을 수정하지 않는다.

사용 예:
    uv run python .claude/skills/experiment-log-lookup/scripts/query_log.py list
    uv run python .claude/skills/experiment-log-lookup/scripts/query_log.py get 038
    uv run python .claude/skills/experiment-log-lookup/scripts/query_log.py search "font size" --log showcase
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

LOG_RELATIVE_PATHS = {
    "experiments": Path("experiments/experiments.json"),
    "showcase": Path("showcase/showcase.json"),
}

PURPOSE_PREVIEW_LEN = 100
SNIPPET_RADIUS = 60


def find_repo_root(start: Path) -> Path:
    """AGENTS.md가 있는 디렉터리를 repo root로 판단해 위로 탐색한다."""
    for candidate in [start, *start.parents]:
        if (candidate / "AGENTS.md").exists():
            return candidate
    raise FileNotFoundError(
        "repo root를 찾지 못했다 (AGENTS.md가 있는 상위 디렉터리가 없다)."
    )


def load_entries(repo_root: Path, log_name: str) -> list[dict[str, Any]]:
    log_path = repo_root / LOG_RELATIVE_PATHS[log_name]
    if not log_path.exists():
        raise FileNotFoundError(f"로그 파일이 없다: {log_path}")
    data = json.loads(log_path.read_text(encoding="utf-8"))
    # experiments.json은 top-level key가 "experiments", showcase.json은 "showcases"다.
    # 첫 번째 list 타입 값을 항목 배열로 사용해 스키마 이름 차이에 대응한다.
    for value in data.values():
        if isinstance(value, list):
            return value
    raise ValueError(f"{log_path}에서 항목 배열을 찾지 못했다.")


def truncate(text: str, length: int) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= length:
        return text
    return text[: length - 1].rstrip() + "…"


def sort_key(entry: dict[str, Any]) -> str:
    match = re.match(r"^(\d+)", str(entry.get("id", "")))
    return match.group(1).zfill(6) if match else str(entry.get("id", ""))


def cmd_list(entries: list[dict[str, Any]], log_name: str) -> None:
    print(f"[{log_name}] {len(entries)}개 항목")
    for entry in sorted(entries, key=sort_key):
        purpose = truncate(str(entry.get("purpose", "")), PURPOSE_PREVIEW_LEN)
        print(f"  {entry.get('id', '?')}: {purpose}")


def match_id(entries: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    query = query.strip()
    exact = [e for e in entries if str(e.get("id", "")) == query]
    if exact:
        return exact
    # 숫자 접두사(예: "038")나 부분 문자열로 매칭한다.
    prefix_matches = [e for e in entries if str(e.get("id", "")).startswith(query)]
    if prefix_matches:
        return prefix_matches
    return [e for e in entries if query.lower() in str(e.get("id", "")).lower()]


def cmd_get(entries: list[dict[str, Any]], log_name: str, query: str) -> None:
    matches = match_id(entries, query)
    if not matches:
        print(f"[{log_name}] '{query}'와 일치하는 id가 없다.")
        return
    if len(matches) > 1:
        print(
            f"[{log_name}] '{query}'에 여러 항목이 일치한다. id를 더 구체적으로 지정하라:"
        )
        for entry in sorted(matches, key=sort_key):
            purpose = truncate(str(entry.get("purpose", "")), PURPOSE_PREVIEW_LEN)
            print(f"  {entry.get('id', '?')}: {purpose}")
        return
    print(json.dumps(matches[0], ensure_ascii=False, indent=2))


def find_snippet(text: str, keyword: str) -> str | None:
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return None
    start = max(0, idx - SNIPPET_RADIUS)
    end = min(len(text), idx + len(keyword) + SNIPPET_RADIUS)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end].replace("\n", " ") + suffix


def cmd_search(
    entries: list[dict[str, Any]],
    log_name: str,
    keyword: str,
    fields: list[str],
) -> None:
    hits: list[tuple[dict[str, Any], str, str]] = []
    for entry in entries:
        for field in fields:
            value = entry.get(field)
            if not isinstance(value, str):
                continue
            snippet = find_snippet(value, keyword)
            if snippet is not None:
                hits.append((entry, field, snippet))
                break
    if not hits:
        print(
            f"[{log_name}] '{keyword}'와 일치하는 항목이 없다 (검색 필드: {', '.join(fields)})."
        )
        return
    print(f"[{log_name}] '{keyword}' 검색 결과 {len(hits)}건")
    for entry, field, snippet in sorted(hits, key=lambda h: sort_key(h[0])):
        print(f"  {entry.get('id', '?')} [{field}]: {snippet}")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    # --log는 서브커맨드 뒤에 붙는 게 자연스러우므로(예: `search "x" --log showcase`)
    # 각 서브파서에 parent로 공유시킨다. top-level parser에는 직접 붙이지 않는다.
    log_parent = argparse.ArgumentParser(add_help=False)
    log_parent.add_argument(
        "--log",
        choices=["experiments", "showcase", "both"],
        default="experiments",
        help="조회할 로그 (기본값: experiments)",
    )

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", parents=[log_parent], help="id와 한 줄 purpose만 나열한다.")

    get_parser = sub.add_parser(
        "get", parents=[log_parent], help="id(또는 숫자 접두사)로 항목 전체를 출력한다."
    )
    get_parser.add_argument("query", help="예: 038 또는 038_full_flow_toc_to_bookmark")

    search_parser = sub.add_parser(
        "search", parents=[log_parent], help="keyword로 id/purpose/finding을 검색한다."
    )
    search_parser.add_argument("keyword")
    search_parser.add_argument(
        "--field",
        choices=["id", "purpose", "finding", "all"],
        default="all",
        help="검색 범위 (기본값: all = id+purpose+finding)",
    )

    args = parser.parse_args()

    repo_root = find_repo_root(Path(__file__).resolve())
    log_names = ["experiments", "showcase"] if args.log == "both" else [args.log]

    for log_name in log_names:
        entries = load_entries(repo_root, log_name)
        if args.command == "list":
            cmd_list(entries, log_name)
        elif args.command == "get":
            cmd_get(entries, log_name, args.query)
        elif args.command == "search":
            fields = (
                ["id", "purpose", "finding"] if args.field == "all" else [args.field]
            )
            cmd_search(entries, log_name, args.keyword, fields)
        if log_name != log_names[-1]:
            print()


if __name__ == "__main__":
    main()
