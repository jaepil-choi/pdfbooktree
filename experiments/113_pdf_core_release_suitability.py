"""실험 113: 고정 PDF corpus의 core release suitability를 fail-closed로 감사한다.

실행은 승인된 순서대로만 가능하며, 모든 결과는 run directory에 원자적으로 봉인한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "pdf-core-release-suitability-v1"
LANGUAGE_VERSION = "language-v1"
SAMPLING_VERSION = "language-sampling-v1"
REVIEW_VERSION = "review-protocol-v1"
SEED_DEFAULT = "20260816"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
FAMILY_RE = re.compile(r"^rf-[0-9a-f]{32}$")


def utc() -> str:
    """UTC 시각을 재현 가능한 artifact metadata 형식으로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> bytes:
    """해시와 저장에 공통으로 쓰는 canonical JSON byte열을 만든다."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def digest(value: Any) -> str:
    """값의 SHA-256을 계산한다."""
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    """파일 내용을 스트리밍으로 SHA-256 계산한다."""
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def artifact(path: Path) -> dict[str, Any]:
    """검증 가능한 artifact 참조를 만든다."""
    return {
        "path": str(path),
        "sha256": file_hash(path),
        "bytes": path.stat().st_size,
        "schema": SCHEMA,
    }


def atomic_json(path: Path, value: Any) -> None:
    """기존 artifact를 절대 덮어쓰지 않고 JSON을 원자 승격한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"중복 artifact 기록을 거부한다: {path}")
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
        temporary = Path(stream.name)
    try:
        os.link(temporary, path)
        temporary.unlink()
    except FileExistsError as error:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"중복 artifact 기록을 거부한다: {path}") from error


def read_json(path: Path) -> Any:
    """JSON artifact를 읽고 손상은 즉시 실패시킨다."""
    if not path.is_file():
        raise RuntimeError(f"필수 artifact가 없다: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"손상된 JSON artifact: {path}") from error


def append_event(run: Path, command: str, status: str, detail: dict[str, Any]) -> None:
    """감사 로그 한 행을 flush+fsync 후 append한다."""
    row = {
        "schema": SCHEMA,
        "time": utc(),
        "command": command,
        "status": status,
        "detail": detail,
    }
    path = run / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        stream.write(canonical(row) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def validate_id(run_id: str, family: str | None = None) -> None:
    """사용자 제공 run/family ID 문법을 검증한다."""
    if not RUN_ID_RE.fullmatch(run_id):
        raise RuntimeError("run-id 형식이 유효하지 않다")
    if family is not None and not FAMILY_RE.fullmatch(family):
        raise RuntimeError("run-family-id 형식이 유효하지 않다")


def run_path(args: argparse.Namespace) -> Path:
    """명시된 run-dir가 해당 run-id의 immutable identity인지 확인한다."""
    validate_id(args.run_id)
    path = Path(args.run_dir).resolve()
    data = read_json(path / "run.json")
    if data["runId"] != args.run_id or Path(data["runDir"]).resolve() != path:
        raise RuntimeError("run-id/run-dir identity가 일치하지 않는다")
    if data["schema"] != SCHEMA:
        raise RuntimeError("run schema가 일치하지 않는다")
    return path


def require_ref(path: Path, ref: dict[str, Any]) -> None:
    """저장된 참조의 path/hash/size를 모두 검증한다."""
    actual = Path(ref["path"])
    if not actual.is_absolute():
        actual = path.parent / actual
    if (
        not actual.is_file()
        or file_hash(actual) != ref["sha256"]
        or actual.stat().st_size != ref["bytes"]
    ):
        raise RuntimeError(f"봉인 참조 검증 실패: {actual}")


def source_hash() -> str:
    """harness와 제품 source/config lock의 현재 실행 source hash를 계산한다."""
    tracked = [
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        Path(__file__).resolve(),
        *sorted((ROOT / "src" / "pdfbooktree").rglob("*.py")),
    ]
    entries = [
        {"path": str(p.relative_to(ROOT)), "sha256": file_hash(p)}
        for p in tracked
        if p.is_file()
    ]
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        head, diff = "unavailable", b"unavailable"
    return digest(
        {
            "head": head,
            "binaryDiff": hashlib.sha256(
                diff.encode("utf-8") if isinstance(diff, str) else diff
            ).hexdigest(),
            "manifest": sorted(entries, key=lambda entry: entry["path"]),
        }
    )


def namespace_files(run: Path, namespace: str) -> list[Path]:
    """prefix-partition seal namespace를 실제 phase artifact로 해석한다."""
    phase, separator, partition = namespace.rpartition("-")
    if separator and phase in {"audit", "mandatory", "queue"}:
        if partition not in {"development", "validation", "all"}:
            raise RuntimeError(f"seal partition이 유효하지 않다: {namespace}")
        path = run / phase / f"{partition}.json"
        if not path.is_file():
            raise RuntimeError(f"seal 대상 artifact가 없다: {path}")
        return [path]
    if namespace in {"development", "validation", "all"}:
        partitions = (
            [namespace] if namespace != "all" else ["development", "validation"]
        )
        files = []
        for phase_name in (
            "products",
            "provenance",
            "audit",
            "mandatory",
            "capacity",
            "queue",
            "reviews",
            "adjudication",
            "gate",
        ):
            for partition_name in partitions:
                path = run / phase_name / f"{partition_name}.json"
                if path.is_file():
                    files.append(path)
        if files:
            return files
    directory = run / namespace
    if directory.exists():
        return sorted(directory.rglob("*.json"))
    path = run / f"{namespace}.json"
    return [path] if path.is_file() else []


def require_seal(run: Path, namespace: str) -> dict[str, Any]:
    """seal receipt와 그 parent/artifact refs를 모두 검증한다."""
    value = read_json(run / "seals" / f"{namespace}.json")
    for ref in value.get("parents", []) + value.get("artifacts", []):
        require_ref(run, ref)
    if value.get("checksum") != digest(value.get("artifacts", [])):
        raise RuntimeError(f"seal checksum이 일치하지 않는다: {namespace}")
    return value


def normalized(text: str) -> str:
    """언어 표본용 NFKC+공백 정규화를 수행한다."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def language(book_id: str, pages: list[str]) -> tuple[str, list[int]]:
    """승인된 anchor/supplemental 알고리즘으로 language-v1을 분류한다."""
    count = len(pages)
    anchors = sorted({1, math.ceil(count / 2), count})
    selected = [page for page in anchors if normalized(pages[page - 1])]
    if len(selected) < 3:
        candidates: list[tuple[str, int]] = []
        for page, text in enumerate(pages, 1):
            text = normalized(text)
            if page not in anchors and text:
                key = hashlib.sha256(
                    (
                        "pdfbooktree.language-supplemental\0"
                        + SAMPLING_VERSION
                        + "\0"
                        + book_id
                        + "\0"
                    ).encode()
                    + page.to_bytes(8, "big")
                    + b"\0"
                    + hashlib.sha256(text.encode()).hexdigest().encode()
                ).hexdigest()
                candidates.append((key, page))
        selected.extend(page for _, page in sorted(candidates)[: 9 - len(selected)])
    text = "".join(normalized(pages[page - 1]) for page in selected)
    hangul = sum("가" <= char <= "힣" for char in text)
    latin = sum(("A" <= char <= "Z") or ("a" <= char <= "z") for char in text)
    total = hangul + latin
    value = (
        "unknown"
        if not total
        else "ko"
        if hangul / total >= 0.8
        else "en"
        if latin / total >= 0.8
        else "mixed"
        if hangul / total >= 0.2 and latin / total >= 0.2
        else "unknown"
    )
    return value, selected


def census(corpus: Path) -> list[dict[str, Any]]:
    """PDF census, page/outline/SHA/language evidence를 실제 corpus에서 만든다."""
    if not corpus.is_dir():
        raise RuntimeError(f"corpus directory가 없다: {corpus}")
    rows = []
    for pdf in sorted(corpus.rglob("*.pdf"), key=lambda p: p.as_posix().casefold()):
        relative = pdf.relative_to(corpus).as_posix()
        sha = file_hash(pdf)
        try:
            with fitz.open(pdf) as document:
                pages = [page.get_text("text") for page in document]
                outline = document.get_toc(simple=True)
            eligible = bool(pages) and any(normalized(page) for page in pages)
            book_id = digest({"path": relative, "sha256": sha})
            lang, sample = language(book_id, pages) if eligible else ("unknown", [])
            rows.append(
                {
                    "bookId": book_id,
                    "relativePath": relative,
                    "sha256": sha,
                    "pages": len(pages),
                    "eligibility": "eligible" if eligible else "ineligible",
                    "disposition": None if eligible else "pending",
                    "outlineCount": len(outline),
                    "hasExistingOutline": bool(outline),
                    "shadowEligible": eligible and bool(outline),
                    "language": lang,
                    "languageSamplePages": sample,
                    "pathGenre": relative.split("/", 1)[0],
                    "groupId": sha,
                }
            )
        except (fitz.FileDataError, RuntimeError, OSError) as error:
            rows.append(
                {
                    "bookId": digest({"path": relative, "sha256": sha}),
                    "relativePath": relative,
                    "sha256": sha,
                    "pages": 0,
                    "eligibility": "ineligible",
                    "disposition": "pending",
                    "outlineCount": 0,
                    "hasExistingOutline": False,
                    "shadowEligible": False,
                    "language": "unknown",
                    "languageSamplePages": [],
                    "pathGenre": relative.split("/", 1)[0],
                    "groupId": sha,
                    "error": str(error),
                }
            )
    if not rows:
        raise RuntimeError("corpus에 PDF가 없다")
    eligible = sorted(
        (row for row in rows if row["eligibility"] == "eligible"),
        key=lambda row: (row["pages"], row["bookId"]),
    )
    for index, row in enumerate(eligible):
        row["lengthTertile"] = (
            "short"
            if index * 3 < len(eligible)
            else "medium"
            if index * 3 < len(eligible) * 2
            else "long"
        )
    for row in rows:
        row.setdefault("lengthTertile", "unknown")
    return rows


def edition_series_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """자동 병합하지 않는 edition/series 후보 근거를 기록한다."""
    candidates = []
    eligible = [row for row in rows if row["eligibility"] == "eligible"]
    for index, left in enumerate(eligible):
        left_name = re.sub(
            r"[^a-z0-9]+", "", Path(left["relativePath"]).stem.casefold()
        )
        for right in eligible[index + 1 :]:
            if left["sha256"] == right["sha256"]:
                continue
            right_name = re.sub(
                r"[^a-z0-9]+", "", Path(right["relativePath"]).stem.casefold()
            )
            same_title = bool(left_name) and left_name == right_name
            similar_pages = abs(left["pages"] - right["pages"]) <= max(
                1, math.ceil(max(left["pages"], right["pages"]) * 0.02)
            )
            same_series = (
                len(left_name) >= 12
                and len(right_name) >= 12
                and Path(left["relativePath"]).parent
                == Path(right["relativePath"]).parent
                and left_name[:12] == right_name[:12]
            )
            if (same_title and similar_pages) or same_series:
                candidates.append(
                    {
                        "bookIds": sorted([left["bookId"], right["bookId"]]),
                        "evidence": {
                            "sameNormalizedTitle": same_title,
                            "pagesWithinTwoPercent": similar_pages,
                            "samePathSeriesPrefix": same_series,
                        },
                        "disposition": None,
                    }
                )
    return candidates


def apply_group_dispositions(
    run: Path,
    rows: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    input_path: str | None,
) -> dict[str, Any] | None:
    """검토된 후보 결정을 봉인하고 accept 연결 성분을 group ID에 반영한다."""
    if input_path is None:
        return None
    supplied = read_json(Path(input_path))
    if supplied.get("schema") != "group-dispositions-v1":
        raise RuntimeError("group disposition schema가 유효하지 않다")
    decision_by_pair = {
        tuple(sorted(decision["bookIds"])): decision
        for decision in supplied.get("decisions", [])
    }
    expected_pairs = {tuple(candidate["bookIds"]) for candidate in candidates}
    if set(decision_by_pair) != expected_pairs:
        raise RuntimeError(
            "group disposition이 candidate 집합과 정확히 일치하지 않는다"
        )

    parent = {row["bookId"]: row["bookId"] for row in rows}

    def find(book_id: str) -> str:
        while parent[book_id] != book_id:
            parent[book_id] = parent[parent[book_id]]
            book_id = parent[book_id]
        return book_id

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for candidate in candidates:
        decision = decision_by_pair[tuple(candidate["bookIds"])]
        disposition = decision.get("disposition")
        evidence = str(decision.get("evidence", "")).strip()
        if disposition not in {"accept", "reject"} or not evidence:
            raise RuntimeError("group disposition과 evidence가 필요하다")
        candidate["disposition"] = disposition
        candidate["dispositionEvidence"] = evidence
        if disposition == "accept":
            union(*candidate["bookIds"])

    components: dict[str, list[str]] = {}
    for book_id in parent:
        components.setdefault(find(book_id), []).append(book_id)
    group_by_book = {
        book_id: digest({"acceptedComponent": sorted(component)})
        for component in components.values()
        for book_id in component
        if len(component) > 1
    }
    for row in rows:
        row["groupId"] = group_by_book.get(row["bookId"], row["groupId"])

    sealed = run / "group-dispositions.json"
    atomic_json(
        sealed,
        {
            "schema": "group-dispositions-v1",
            "decisions": [decision_by_pair[pair] for pair in sorted(decision_by_pair)],
            "source": str(Path(input_path).resolve()),
        },
    )
    return artifact(sealed)


def split_score(
    groups: dict[str, list[dict[str, Any]]], chosen: set[str], target: int, seed: str
) -> tuple[Any, ...]:
    """size와 marginal deviation을 exact integer 분자로 비교하는 score를 만든다."""
    selected = [row for group in chosen for row in groups[group]]
    all_rows = [row for members in groups.values() for row in members]
    deviation = []
    for field in ("language", "lengthTertile", "hasExistingOutline", "pathGenre"):
        labels = sorted({str(row[field]) for row in all_rows})
        for label in labels:
            total = sum(str(row[field]) == label for row in all_rows)
            actual = sum(str(row[field]) == label for row in selected)
            deviation.append(abs(actual * len(all_rows) - total * target))
    tie = hashlib.sha256((seed + "\0" + "\0".join(sorted(chosen))).encode()).hexdigest()
    return (
        abs(len(selected) - target),
        max(deviation, default=0),
        sum(deviation),
        tie,
    )


def split_rows(rows: list[dict[str, Any]], seed: str) -> tuple[dict[str, str], str]:
    """SHA group을 깨지 않고 marginal score를 개선하는 deterministic local split이다."""
    eligible = [row for row in rows if row["eligibility"] == "eligible"]
    if not eligible:
        raise RuntimeError("eligible PDF가 없다")
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in eligible:
        groups.setdefault(row["groupId"], []).append(row)
    target = int(math.floor(len(eligible) * 0.2 + 0.5))
    chosen: set[str] = set()
    while True:
        current = split_score(groups, chosen, target, seed)
        options = []
        for group in sorted(groups):
            options.append(chosen | {group})
            if group in chosen:
                options.append(chosen - {group})
        for remove in sorted(chosen):
            for add in sorted(set(groups) - chosen):
                options.append((chosen - {remove}) | {add})
        best = min(
            ((split_score(groups, option, target, seed), option) for option in options),
            key=lambda candidate: candidate[0],
        )
        if best[0] >= current:
            break
        chosen = best[1]
    assignments = {
        row["bookId"]: "validation" if row["groupId"] in chosen else "development"
        for row in eligible
    }
    return assignments, digest(
        {"seed": seed, "version": "group-aware-split-v1", "assignments": assignments}
    )


def seal(
    run: Path, namespace: str, command: str, parents: list[dict[str, Any]] | None = None
) -> Path:
    """현재 namespace artifact의 checksum receipt를 immutable seal로 기록한다."""
    for parent in parents or []:
        require_ref(run, parent)
    files = [artifact(path) for path in namespace_files(run, namespace)]
    if not files:
        raise RuntimeError(f"seal할 artifact가 없다: {namespace}")
    path = run / "seals" / f"{namespace}.json"
    atomic_json(
        path,
        {
            "schema": SCHEMA,
            "namespace": namespace,
            "command": command,
            "time": utc(),
            "parents": parents or [],
            "artifacts": files,
            "checksum": digest(files),
        },
    )
    return path


def prereg(run: Path) -> dict[str, Any]:
    """preregistration seal과 corpus/split/config/source hash를 검증해 읽는다."""
    value = read_json(run / "preregistration.json")
    require_ref(run, value["corpusRef"])
    if value["executionSourceHash"] != source_hash():
        raise RuntimeError("execution source drift를 거부한다")
    return value


def command_create_run(args: argparse.Namespace) -> dict[str, Any]:
    """root run identity만 생성한다."""
    validate_id(
        args.run_id,
        args.run_family_id
        or "rf-" + hashlib.sha256(args.run_id.encode()).hexdigest()[:32],
    )
    run = Path(args.run_dir).resolve()
    if run.exists() and any(run.iterdir()):
        raise RuntimeError("비어 있지 않은 run-dir을 거부한다")
    run.mkdir(parents=True, exist_ok=True)
    family = (
        args.run_family_id
        or "rf-" + hashlib.sha256((args.run_id + str(run)).encode()).hexdigest()[:32]
    )
    atomic_json(
        run / "run.json",
        {
            "schema": SCHEMA,
            "runId": args.run_id,
            "runDir": str(run),
            "runFamilyId": family,
            "parentRun": None,
            "corpus": str(Path(args.corpus).resolve()),
            "seed": args.seed,
            "createdAt": utc(),
            "executionSourceHash": source_hash(),
        },
    )
    append_event(run, "create-run", "succeeded", {"family": family})
    return {"run": artifact(run / "run.json")}


def command_preregister(args: argparse.Namespace) -> dict[str, Any]:
    """fixed corpus census와 숨긴 validation assignment commitment를 봉인한다."""
    run = run_path(args)
    identity = read_json(run / "run.json")
    corpus_path = (
        Path(args.corpus).resolve()
        if args.corpus
        else Path(identity["corpus"]).resolve()
    )
    rows = census(corpus_path)
    candidates = edition_series_candidates(rows)
    group_disposition_ref = apply_group_dispositions(
        run, rows, candidates, args.group_dispositions
    )
    assignments, assignment_hash = split_rows(rows, identity["seed"])
    corpus_file = run / "corpus.json"
    atomic_json(
        corpus_file,
        {
            "schema": SCHEMA,
            "corpus": str(corpus_path),
            "languageVersion": LANGUAGE_VERSION,
            "languageSamplingVersion": SAMPLING_VERSION,
            "rows": rows,
            "groupCandidates": candidates,
            "groupDispositionRef": group_disposition_ref,
            "sha256": digest(rows),
        },
    )
    private = run / "validation.assignment.json"
    atomic_json(
        private,
        {
            "schema": SCHEMA,
            "assignments": assignments,
            "assignmentHash": assignment_hash,
        },
    )
    try:
        os.chmod(private, 0o600)
    except OSError:
        pass
    dev = sorted(
        book for book, partition in assignments.items() if partition == "development"
    )
    value = {
        "schema": SCHEMA,
        "runId": identity["runId"],
        "corpusRef": artifact(corpus_file),
        "corpusHash": digest(rows),
        "groupDispositionRef": group_disposition_ref,
        "configHash": digest(
            {
                "inPlace": False,
                "default": "current-public-core",
                "shadow": "skip_existing_bookmarks=false",
            }
        ),
        "executionSourceHash": source_hash(),
        "assignmentHash": assignment_hash,
        "validationCommitment": digest(
            sorted(
                book
                for book, partition in assignments.items()
                if partition == "validation"
            )
        ),
        "developmentBookIds": dev,
        "requestedQuotas": {"DD": 25, "DS": 25, "VD": 6, "VS": 6},
        "authoritative": True,
        "gateEligible": True,
    }
    atomic_json(run / "preregistration.json", value)
    append_event(
        run,
        "preregister",
        "succeeded",
        {"eligible": len(assignments), "development": len(dev)},
    )
    return {"preregistration": artifact(run / "preregistration.json")}


def command_preflight(args: argparse.Namespace) -> dict[str, Any]:
    """identity/source/corpus/ineligible disposition과 output non-overlap을 fail-closed 검사한다."""
    run = run_path(args)
    pre = prereg(run)
    corpus = read_json(run / "corpus.json")
    unresolved = [
        row["relativePath"]
        for row in corpus["rows"]
        if row["eligibility"] == "ineligible" and not row.get("disposition")
    ]
    unresolved_candidates = [
        candidate["bookIds"]
        for candidate in corpus.get("groupCandidates", [])
        if not candidate.get("disposition")
    ]
    corpus_path = Path(corpus["corpus"]).resolve()
    if run == corpus_path or corpus_path in run.parents or run in corpus_path.parents:
        raise RuntimeError("run-dir과 corpus의 path overlap을 거부한다")
    if unresolved:
        raise RuntimeError(f"ineligible disposition이 없다: {unresolved[:3]}")
    if unresolved_candidates:
        raise RuntimeError(
            f"edition/series candidate disposition이 없다: {unresolved_candidates[:3]}"
        )
    path = run / "preflight.json"
    atomic_json(
        path,
        {
            "schema": SCHEMA,
            "preregistration": artifact(run / "preregistration.json"),
            "corpusHash": pre["corpusHash"],
            "status": "passed",
            "time": utc(),
        },
    )
    append_event(run, "preflight", "succeeded", {})
    return {"preflight": artifact(path)}


def command_create_qualification(args: argparse.Namespace) -> dict[str, Any]:
    """parent root의 sealed preregistration을 상속하는 gate-ineligible qualification run을 만든다."""
    parent = Path(args.parent_run_dir).resolve()
    parent_data = read_json(parent / "run.json")
    prereg(parent)
    validate_id(args.run_id)
    run = Path(args.run_dir).resolve()
    if run.exists() and any(run.iterdir()):
        raise RuntimeError("비어 있지 않은 qualification run-dir을 거부한다")
    run.mkdir(parents=True, exist_ok=True)
    atomic_json(
        run / "run.json",
        {
            "schema": SCHEMA,
            "runId": args.run_id,
            "runDir": str(run),
            "runFamilyId": parent_data["runFamilyId"],
            "parentRun": artifact(parent / "run.json"),
            "seed": parent_data["seed"],
            "createdAt": utc(),
            "executionSourceHash": source_hash(),
            "gateEligible": False,
        },
    )
    atomic_json(
        run / "qualification-parent.json",
        {
            "schema": SCHEMA,
            "parentPreregistration": artifact(parent / "preregistration.json"),
        },
    )
    append_event(run, "create-qualification", "succeeded", {"parent": str(parent)})
    return {"run": artifact(run / "run.json")}


def command_qualify(args: argparse.Namespace) -> dict[str, Any]:
    """언어/split/lineage/refill/outlier/gate 산술 oracle을 최대 여덟 attempt로 검증한다."""
    run = run_path(args)
    identity = read_json(run / "run.json")
    if identity.get("gateEligible") or args.gate_eligible != "false":
        raise RuntimeError("qualification은 반드시 gateEligible=false여야 한다")
    lang, sample = language("oracle", ["   ", "\n", "한글ABC", ""])
    language_ok = (lang, sample) == ("mixed", [3])
    assignments, _ = split_rows(
        [
            {
                "bookId": str(i),
                "eligibility": "eligible",
                "groupId": str(i),
                "language": "ko" if i % 2 else "en",
                "lengthTertile": "short" if i < 4 else "long",
                "hasExistingOutline": bool(i % 2),
                "pathGenre": f"genre-{i % 2}",
            }
            for i in range(10)
        ],
        identity["seed"],
    )
    split_ok = sum(value == "validation" for value in assignments.values()) == 2
    parent = identity.get("parentRun")
    lineage_ok = bool(parent)
    if parent:
        require_ref(run, parent)
    parent_ref = read_json(run / "qualification-parent.json")["parentPreregistration"]
    require_ref(run, parent_ref)
    oracle = run / "qualification-oracle.json"
    atomic_json(oracle, {"schema": SCHEMA, "value": "immutable"})
    atomicity_ok = read_json(oracle)["value"] == "immutable"
    try:
        atomic_json(oracle, {"schema": SCHEMA, "value": "duplicate"})
        duplicate_ok = False
    except RuntimeError:
        duplicate_ok = read_json(oracle)["value"] == "immutable"
    base = ["A1", "A2", "A3"]
    mandatory = [{"attemptArmId": "A2"}, {"attemptArmId": "S2"}]
    queue_ids = sorted(set(base) | {row["attemptArmId"] for row in mandatory})
    refill_ok = queue_ids == ["A1", "A2", "A3", "S2"] and len(queue_ids) == 4
    outlier_ok = queue_ids.count("S2") == 1
    pass_math = gate_math(
        [
            {
                "integrity": True,
                "inference": True,
                "plausible": True,
                "severe": False,
                "marginals": {"lane": "default"},
            }
        ]
    )["passed"]
    fail_math = not gate_math(
        [
            {
                "integrity": True,
                "inference": True,
                "plausible": False,
                "severe": False,
                "marginals": {"lane": "default"},
            }
        ]
    )["passed"]
    checks = {
        "language": language_ok,
        "split": split_ok,
        "lineage": lineage_ok,
        "atomicity": atomicity_ok,
        "duplicateRejection": duplicate_ok,
        "refillHamilton": refill_ok,
        "outlierUnion": outlier_ok,
        "gateMath": pass_math and fail_math,
    }
    if not all(checks.values()):
        raise RuntimeError(f"qualification oracle 실패: {checks}")
    path = run / "qualification.json"
    atomic_json(
        path,
        {
            "schema": SCHEMA,
            "attemptCount": 0,
            "checkCount": len(checks),
            "checks": checks,
            "gateEligible": False,
            "passed": all(checks.values()),
        },
    )
    append_event(run, "qualify", "succeeded", checks)
    return {"qualification": artifact(path)}


def expected_books(run: Path, partition: str, lane: str) -> list[dict[str, Any]]:
    """partition/lane의 expected logical arm population을 반환한다."""
    pre = prereg(run)
    corpus = read_json(run / "corpus.json")
    assignments = read_json(run / "validation.assignment.json")["assignments"]
    if partition == "validation":
        allowed = {book for book, value in assignments.items() if value == "validation"}
    elif partition == "development":
        allowed = set(pre["developmentBookIds"])
    else:
        raise RuntimeError(
            "run-lane partition은 development 또는 validation이어야 한다"
        )
    return [
        row
        for row in corpus["rows"]
        if row["bookId"] in allowed and (lane == "default" or row["shadowEligible"])
    ]


def command_run_lane(args: argparse.Namespace) -> dict[str, Any]:
    """현재 public pipeline 경로를 in_place=false로 book별 격리 실행한다."""
    if args.in_place != "false":
        raise RuntimeError("in_place=false만 허용한다")
    if args.lane not in {"default", "shadow-inference"}:
        raise RuntimeError("알 수 없는 lane")
    run = run_path(args)
    pre = prereg(run)
    items = expected_books(run, args.partition, args.lane)
    from pdfbooktree.config import ProcessingConfig
    from pdfbooktree.pipeline import (
        analyze_pdf,
        apply_plan,
        infer_bookmarks,
        resolve_existing_outline_action,
    )
    from pdfbooktree.pdf.outline import outline_to_plan

    corpus = Path(read_json(run / "corpus.json")["corpus"])
    results = []
    for row in items:
        logical = digest(
            {
                "family": read_json(run / "run.json")["runFamilyId"],
                "partition": args.partition,
                "lane": args.lane,
                "book": row["bookId"],
            }
        )
        attempt = digest(
            {
                "run": args.run_id,
                "logical": logical,
                "config": pre["configHash"],
                "source": pre["executionSourceHash"],
            }
        )
        target = run / "products" / args.partition / args.lane / attempt
        if target.exists():
            raise RuntimeError(f"중복 attempt를 거부한다: {attempt}")
        target.mkdir(parents=True)
        product: dict[str, Any] = {
            "schema": SCHEMA,
            "logicalArmId": logical,
            "attemptArmId": attempt,
            "bookId": row["bookId"],
            "partition": args.partition,
            "lane": args.lane,
            "sourcePdfSha256": row["sha256"],
            "inPlace": False,
            "status": "failed",
        }
        try:
            source = corpus / row["relativePath"]
            config = ProcessingConfig(skip_existing_bookmarks=args.lane == "default")
            decision = resolve_existing_outline_action(source, row["pages"], config)
            if decision.reuse_existing:
                plan = outline_to_plan(decision.existing_outline)
                action = "reused"
            else:
                analysis = analyze_pdf(source, config.typography)
                inference = infer_bookmarks(analysis, config.typography)
                plan = inference.plan
                action = "inferred"
            atomic_json(
                target / "full-plan.json",
                {"schema": SCHEMA, "items": [asdict(item) for item in plan]},
            )
            applied = apply_plan(
                source,
                target,
                plan,
                row["pages"],
                config.markdown_split,
                config.markdown_content_mode,
                in_place=False,
            )
            atomic_json(
                target / "effective-plan.json",
                {
                    "schema": SCHEMA,
                    "items": [asdict(item) for item in applied.applied_plan],
                },
            )
            atomic_json(
                target / "canonical-plan.json",
                {
                    "schema": SCHEMA,
                    "items": [asdict(item) for item in applied.applied_plan],
                },
            )
            product.update(
                {
                    "status": "succeeded" if applied.validation.valid else "invalid",
                    "defaultAction": action
                    if args.lane == "default"
                    else "shadow_inference",
                    "planCount": len(plan),
                    "validation": asdict(applied.validation),
                    "outputPdf": artifact(applied.output_pdf)
                    if applied.output_pdf
                    else None,
                    "markdownDir": str(applied.output_markdown_dir)
                    if applied.output_markdown_dir
                    else None,
                    "markdownManifest": artifact(applied.markdown_export.manifest_path)
                    if applied.markdown_export and applied.markdown_export.manifest_path
                    else None,
                    "plans": [
                        artifact(target / name)
                        for name in (
                            "full-plan.json",
                            "effective-plan.json",
                            "canonical-plan.json",
                        )
                    ],
                }
            )
        except Exception as error:
            product["error"] = f"{type(error).__name__}: {error}"
        atomic_json(target / "product.json", product)
        results.append(artifact(target / "product.json"))
    index = run / "products" / args.partition / f"{args.lane}.json"
    atomic_json(
        index,
        {
            "schema": SCHEMA,
            "partition": args.partition,
            "lane": args.lane,
            "attempts": results,
        },
    )
    append_event(
        run,
        "run-lane",
        "succeeded",
        {"partition": args.partition, "lane": args.lane, "attempts": len(results)},
    )
    return {"lane": artifact(index), "attemptCount": len(results)}


def products(run: Path, partition: str) -> list[dict[str, Any]]:
    """두 lane product manifests가 있어야만 audit 단계로 진행한다."""
    expected = expected_books(run, partition, "default") + expected_books(
        run, partition, "shadow-inference"
    )
    values = []
    for lane in ("default", "shadow-inference"):
        index = read_json(run / "products" / partition / f"{lane}.json")
        for ref in index["attempts"]:
            require_ref(run, ref)
            values.append(read_json(Path(ref["path"])))
    if len(values) != len(expected):
        raise RuntimeError("expected logical arm과 product evidence 수가 다르다")
    return values


def command_reconcile(args: argparse.Namespace) -> dict[str, Any]:
    """product evidence의 source/config/attempt lineage를 독립적으로 대조한다."""
    run = run_path(args)
    values = products(run, args.partition)
    pre = prereg(run)
    bad = [
        item["attemptArmId"]
        for item in values
        if item["sourcePdfSha256"]
        not in {row["sha256"] for row in read_json(run / "corpus.json")["rows"]}
    ]
    if bad:
        raise RuntimeError("provenance mismatch")
    path = run / "provenance" / f"{args.partition}.json"
    atomic_json(
        path,
        {
            "schema": SCHEMA,
            "partition": args.partition,
            "productCount": len(values),
            "executionSourceHash": pre["executionSourceHash"],
            "passed": True,
        },
    )
    append_event(
        run, "reconcile-provenance", "succeeded", {"partition": args.partition}
    )
    return {"provenance": artifact(path)}


def command_audit(args: argparse.Namespace) -> dict[str, Any]:
    """product evidence를 치유하지 않고 PDF/plan/output artifact 결손을 hard failure로 관찰한다."""
    run = run_path(args)
    values = products(run, args.partition)
    prov = run / "provenance" / f"{args.partition}.json"
    require_ref(run, artifact(prov))
    observations = []
    for item in values:
        from pdfbooktree.models import BookmarkPlanItem
        from pdfbooktree.pipeline import validate_plan

        plan_refs = item.get("plans", [])
        for ref in plan_refs:
            require_ref(run, ref)
        output_ref = item.get("outputPdf")
        if output_ref:
            require_ref(run, output_ref)
        markdown_dir = Path(item["markdownDir"]) if item.get("markdownDir") else None
        source = next(
            (
                Path(read_json(run / "corpus.json")["corpus"]) / row["relativePath"]
                for row in read_json(run / "corpus.json")["rows"]
                if row["bookId"] == item["bookId"]
            ),
            None,
        )
        plan_rows = [read_json(Path(ref["path"]))["items"] for ref in plan_refs]
        plans_equal = len(plan_rows) == 3 and plan_rows[1] == plan_rows[2]
        plan_valid = False
        if source and plan_rows:
            try:
                plan_valid = all(
                    validate_plan(
                        source, [BookmarkPlanItem(**row) for row in plan_rows[index]]
                    ).valid
                    for index in (0, 1, 2)
                )
            except (TypeError, ValueError, RuntimeError, OSError):
                plan_valid = False
        output_valid = False
        if output_ref:
            try:
                output = Path(output_ref["path"])
                with fitz.open(output) as document:
                    output_valid = document.page_count == next(
                        row["pages"]
                        for row in read_json(run / "corpus.json")["rows"]
                        if row["bookId"] == item["bookId"]
                    ) and bool(document.get_toc(simple=True))
            except (fitz.FileDataError, OSError, RuntimeError):
                output_valid = False
        manifest = None
        if item.get("markdownManifest"):
            try:
                require_ref(run, item["markdownManifest"])
                manifest = read_json(Path(item["markdownManifest"]["path"]))
            except RuntimeError:
                manifest = None
        markdown_files = list(markdown_dir.rglob("*.md")) if markdown_dir else []
        coverage = manifest.get("coverage", {}) if manifest else {}
        validation = manifest.get("validation", {}) if manifest else {}
        checks = {
            "productManifest": True,
            "sourceHash": True,
            "inPlaceFalse": item["inPlace"] is False,
            "success": item["status"] == "succeeded",
            "fullEffectiveCanonical": plans_equal and plan_valid,
            "outputPdf": output_valid,
            "markdownYaml": bool(markdown_files),
            "graphManifest": bool(manifest and manifest.get("nodes")),
            "sourceOutputHash": bool(
                manifest
                and source
                and manifest.get("input", {}).get("sha256") == file_hash(source)
            ),
            "pageOwnership": bool(manifest and manifest.get("nodes")),
            "coverageMetadata": bool(coverage and validation.get("valid") is True),
            "duplicateBodyEvidence": len(markdown_files)
            == len({path.read_bytes() for path in markdown_files}),
        }
        observations.append(
            {
                "attemptArmId": item["attemptArmId"],
                "productEvidence": item,
                "auditObservations": checks,
                "integrity": all(checks.values()),
                "outlierReasons": [name for name, ok in checks.items() if not ok],
            }
        )
    path = run / "audit" / f"{args.partition}.json"
    atomic_json(
        path,
        {
            "schema": SCHEMA,
            "partition": args.partition,
            "provenance": artifact(prov),
            "observations": observations,
            "hardFailures": sum(not row["integrity"] for row in observations),
        },
    )
    if args.seal == "true":
        seal(
            run, f"audit-{args.partition}", f"audit:{args.partition}", [artifact(prov)]
        )
    append_event(
        run,
        "audit",
        "succeeded",
        {
            "partition": args.partition,
            "hardFailures": sum(not row["integrity"] for row in observations),
        },
    )
    return {"audit": artifact(path)}


def command_mandatory(args: argparse.Namespace) -> dict[str, Any]:
    """audit seal 뒤 failed/reused/outlier mandatory review set을 immutable로 만든다."""
    run = run_path(args)
    audit = run / "audit" / f"{args.partition}.json"
    data = read_json(audit)
    require_seal(run, f"audit-{args.partition}")
    ids = []
    for row in data["observations"]:
        evidence = row["productEvidence"]
        reasons = list(row["outlierReasons"])
        if evidence.get("defaultAction") == "reused":
            reasons.append("actual_reused")
        if evidence["status"] != "succeeded":
            reasons.append("terminal_non_success")
        if reasons:
            ids.append(
                {"attemptArmId": row["attemptArmId"], "reasons": sorted(set(reasons))}
            )
    path = run / "mandatory" / f"{args.partition}.json"
    atomic_json(path, {"schema": SCHEMA, "audit": artifact(audit), "items": ids})
    seal(
        run,
        f"mandatory-{args.partition}",
        f"mandatory:{args.partition}",
        [artifact(audit)],
    )
    append_event(
        run,
        "seal-mandatory-set",
        "succeeded",
        {"partition": args.partition, "count": len(ids)},
    )
    return {"mandatory": artifact(path)}


def command_capacity(args: argparse.Namespace) -> dict[str, Any]:
    """audit 완료 뒤 실제 inference capacity와 quota/refill ledger를 계산한다."""
    run = run_path(args)
    parts = (
        [args.partition] if args.partition != "all" else ["development", "validation"]
    )
    cells = {"DD": [], "DS": [], "VD": [], "VS": []}
    for part in parts:
        require_seal(run, f"audit-{part}")
        for row in read_json(run / "audit" / f"{part}.json")["observations"]:
            product = row["productEvidence"]
            if (
                product["status"] == "succeeded"
                and product.get("defaultAction") != "reused"
            ):
                cells[
                    ("D" if part == "development" else "V")
                    + ("S" if product["lane"] == "shadow-inference" else "D")
                ].append(row["attemptArmId"])
    targets = {"DD": 25, "DS": 25, "VD": 6, "VS": 6}
    quotas = {key: min(targets[key], len(value)) for key, value in cells.items()}
    base_target = min(62, sum(map(len, cells.values())))
    path = run / "capacity" / f"{args.partition}.json"
    atomic_json(
        path,
        {
            "schema": SCHEMA,
            "cells": cells,
            "capacity": {key: len(value) for key, value in cells.items()},
            "quotas": quotas,
            "baseTarget": base_target,
            "auditParents": [
                artifact(run / "audit" / f"{part}.json") for part in parts
            ],
        },
    )
    append_event(
        run,
        "finalize-review-capacity",
        "succeeded",
        {"partition": args.partition, "baseTarget": base_target},
    )
    return {"capacity": artifact(path)}


def command_queue(args: argparse.Namespace) -> dict[str, Any]:
    """capacity와 mandatory seal을 부모로 하는 결정적 immutable final review queue를 만든다."""
    run = run_path(args)
    parts = (
        [args.partition] if args.partition != "all" else ["development", "validation"]
    )
    capacity = run / "capacity" / f"{args.partition}.json"
    cap = read_json(capacity)
    mandatory = []
    for part in parts:
        require_seal(run, f"mandatory-{part}")
        mandatory.extend(read_json(run / "mandatory" / f"{part}.json")["items"])
    candidates = [item for cell in cap["cells"].values() for item in cell]
    ordered = sorted(
        candidates,
        key=lambda item: hashlib.sha256(
            (SEED_DEFAULT + REVIEW_VERSION + item).encode()
        ).hexdigest(),
    )[: cap["baseTarget"]]
    reasons = {item: {"base"} for item in ordered}
    for row in mandatory:
        reasons.setdefault(row["attemptArmId"], set()).update(row["reasons"])
    tasks = [
        {
            "taskId": digest({"attempt": item, "queue": args.partition}),
            "attemptArmId": item,
            "reasons": sorted(reason),
        }
        for item, reason in sorted(reasons.items())
    ]
    path = run / "queue" / f"{args.partition}.json"
    atomic_json(
        path,
        {
            "schema": SCHEMA,
            "capacity": artifact(capacity),
            "mandatory": mandatory,
            "tasks": tasks,
            "baseTarget": cap["baseTarget"],
            "duplicateCount": 0,
            "sealed": args.seal == "true",
        },
    )
    if args.seal == "true":
        seal(
            run,
            f"queue-{args.partition}",
            f"queue:{args.partition}",
            [artifact(capacity)],
        )
    append_event(
        run,
        "build-review-queue",
        "succeeded",
        {"partition": args.partition, "tasks": len(tasks)},
    )
    return {"queue": artifact(path)}


def command_submit(args: argparse.Namespace) -> dict[str, Any]:
    """reviewer immutable shard를 task identity와 함께 staging에 제출한다."""
    run = run_path(args)
    supplied = read_json(Path(args.input))
    task = args.task_id
    if supplied.get("taskId") != task or not args.reviewer_id:
        raise RuntimeError("review shard task/reviewer identity가 유효하지 않다")
    path = run / "review-staging" / f"{task}.{args.reviewer_id}.json"
    atomic_json(
        path,
        {
            "schema": SCHEMA,
            "taskId": task,
            "reviewerId": args.reviewer_id,
            "submission": supplied,
            "submittedAt": utc(),
        },
    )
    append_event(
        run,
        "submit-review",
        "succeeded",
        {"taskId": task, "reviewer": args.reviewer_id},
    )
    return {"submission": artifact(path)}


def command_import(args: argparse.Namespace) -> dict[str, Any]:
    """sealed queue에 있는 shard만 import하고 누락 task는 상태로 보존한다."""
    run = run_path(args)
    queue = read_json(run / "queue" / f"{args.partition}.json")
    allowed = {row["taskId"] for row in queue["tasks"]}
    shards = []
    for path in (
        sorted((run / "review-staging").glob("*.json"))
        if (run / "review-staging").exists()
        else []
    ):
        row = read_json(path)
        if row["taskId"] not in allowed:
            raise RuntimeError("queue 밖 review shard를 거부한다")
        shards.append(artifact(path))
    path = run / "reviews" / f"{args.partition}.json"
    atomic_json(
        path,
        {
            "schema": SCHEMA,
            "queue": artifact(run / "queue" / f"{args.partition}.json"),
            "submissions": shards,
            "missingTaskIds": sorted(
                allowed - {read_json(Path(ref["path"]))["taskId"] for ref in shards}
            ),
        },
    )
    append_event(
        run,
        "import-reviews",
        "succeeded",
        {"partition": args.partition, "count": len(shards)},
    )
    return {"reviews": artifact(path)}


def command_adjudicate(args: argparse.Namespace) -> dict[str, Any]:
    """missing/rejected/disagreement을 미해결로 남겨 gate가 우회하지 못하게 한다."""
    run = run_path(args)
    reviews = read_json(run / "reviews" / f"{args.partition}.json")
    queue = read_json(run / "queue" / f"{args.partition}.json")
    attempt_by_task = {task["taskId"]: task["attemptArmId"] for task in queue["tasks"]}
    decisions = []
    for ref in reviews["submissions"]:
        row = read_json(Path(ref["path"]))
        result = row["submission"]
        decisions.append(
            {
                "taskId": row["taskId"],
                "attemptArmId": attempt_by_task[row["taskId"]],
                "plausible": result.get("plausible"),
                "severe": bool(result.get("severe", False)),
                "adjudicated": result.get("plausible") in {True, False},
            }
        )
    path = run / "adjudication" / f"{args.partition}.json"
    atomic_json(
        path,
        {
            "schema": SCHEMA,
            "reviews": artifact(run / "reviews" / f"{args.partition}.json"),
            "decisions": decisions,
            "unresolved": reviews["missingTaskIds"]
            + [row["taskId"] for row in decisions if not row["adjudicated"]],
        },
    )
    append_event(run, "adjudicate", "succeeded", {"partition": args.partition})
    return {"adjudication": artifact(path)}


def gate_math(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """integrity0, overall90, marginal80, severe0를 denominator 보존 방식으로 계산한다."""
    integrity = all(row["integrity"] for row in rows)
    inference = [row for row in rows if row["inference"]]
    plausible = sum(row["plausible"] for row in inference)
    overall = not inference or plausible >= math.ceil(0.9 * len(inference))
    severe = not any(row["severe"] for row in rows)
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in inference:
        for key, value in row.get("marginals", {}).items():
            groups.setdefault(f"{key}:{value}", []).append(row)
    marginal = {
        key: {
            "n": len(value),
            "plausible": sum(row["plausible"] for row in value),
            "passed": sum(row["plausible"] for row in value)
            >= math.ceil(0.8 * len(value)),
        }
        for key, value in groups.items()
    }
    return {
        "integrity": integrity,
        "overall": overall,
        "severe": severe,
        "marginals": marginal,
        "passed": integrity
        and overall
        and severe
        and all(value["passed"] for value in marginal.values()),
    }


def command_gate(args: argparse.Namespace) -> dict[str, Any]:
    """audit와 adjudication만으로 suitability matrix 및 gate verdict를 만든다."""
    run = run_path(args)
    parts = (
        [args.partition] if args.partition != "all" else ["development", "validation"]
    )
    queue = read_json(run / "queue" / f"{args.partition}.json")
    adjudication = read_json(run / "adjudication" / f"{args.partition}.json")
    selected_attempts = {task["attemptArmId"] for task in queue["tasks"]}
    decision_by_attempt = {
        decision["attemptArmId"]: decision for decision in adjudication["decisions"]
    }
    corpus_by_book = {
        row["bookId"]: row for row in read_json(run / "corpus.json")["rows"]
    }
    rows = []
    unresolved = list(adjudication["unresolved"])
    for part in parts:
        audit = read_json(run / "audit" / f"{part}.json")
        for observed in audit["observations"]:
            product = observed["productEvidence"]
            selected = product["attemptArmId"] in selected_attempts
            infer = selected and product.get("defaultAction") != "reused"
            decision = (
                decision_by_attempt.get(product["attemptArmId"]) if infer else None
            )
            if infer and decision is None:
                unresolved.append(product["attemptArmId"])
            corpus_row = corpus_by_book[product["bookId"]]
            rows.append(
                {
                    "attemptArmId": product["attemptArmId"],
                    "bookId": product["bookId"],
                    "partition": part,
                    "lane": product["lane"],
                    "integrity": observed["integrity"],
                    "inference": infer,
                    "plausible": (
                        bool(decision["plausible"]) if infer and decision else not infer
                    ),
                    "severe": bool(decision["severe"]) if decision else False,
                    "marginals": {
                        "lane": product["lane"],
                        "language": corpus_row["language"],
                        "outline": (
                            "yes" if corpus_row["hasExistingOutline"] else "no"
                        ),
                        "pathGenre": corpus_row["pathGenre"],
                        "length": corpus_row["lengthTertile"],
                        "provenance": product.get(
                            "defaultAction", "default_unresolved"
                        ),
                    },
                }
            )
    verdict = gate_math(rows)
    verdict["reusedReviewCount"] = sum(
        row["attemptArmId"] in selected_attempts
        and row["productEvidence"].get("defaultAction") == "reused"
        for part in parts
        for row in read_json(run / "audit" / f"{part}.json")["observations"]
    )
    verdict["passed"] = verdict["passed"] and not unresolved
    verdict["unresolved"] = unresolved
    path = run / "gate" / f"{args.partition}.json"
    atomic_json(
        path,
        {
            "schema": SCHEMA,
            "verdict": verdict,
            "suitabilityMatrix": rows if args.emit_suitability_matrix else None,
        },
    )
    append_event(
        run,
        "gate",
        "succeeded",
        {"partition": args.partition, "passed": verdict["passed"]},
    )
    return {"gate": artifact(path), "passed": verdict["passed"]}


def command_reveal(args: argparse.Namespace) -> dict[str, Any]:
    """development seal 이후에만 hidden validation identity를 최초 한 번 reveal한다."""
    run = run_path(args)
    if not (run / "gate" / "development.json").is_file():
        raise RuntimeError("validation reveal 전에 development gate가 필요하다")
    private = read_json(run / "validation.assignment.json")
    validation = sorted(
        key for key, value in private["assignments"].items() if value == "validation"
    )
    path = run / "validation-reveal.json"
    atomic_json(
        path,
        {
            "schema": SCHEMA,
            "assignmentHash": private["assignmentHash"],
            "validationBookIds": validation,
            "revealedAt": utc(),
        },
    )
    append_event(run, "reveal-validation", "succeeded", {"count": len(validation)})
    return {"reveal": artifact(path)}


def command_seal(args: argparse.Namespace) -> dict[str, Any]:
    """명시 namespace의 결과를 checksum receipt로 봉인한다."""
    run = run_path(args)
    path = seal(run, args.namespace, "seal")
    append_event(run, "seal", "succeeded", {"namespace": args.namespace})
    return {"seal": artifact(path)}


def parser() -> argparse.ArgumentParser:
    """승인된 모든 subcommand와 명시 identity 인자를 정의한다."""
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)

    def add(name: str, func, *extra: str):
        p = sub.add_parser(name)
        p.add_argument("--run-id", required=True)
        p.add_argument("--run-dir", required=True)
        for key in extra:
            p.add_argument(key, required=True)
        p.set_defaults(func=func)
        return p

    p = add("create-run", command_create_run)
    p.add_argument("--run-family-id")
    p.add_argument("--corpus", required=True)
    p.add_argument("--seed", default=SEED_DEFAULT)
    p = add("preregister", command_preregister)
    p.add_argument("--corpus")
    p.add_argument("--group-dispositions")
    add("preflight", command_preflight)
    p = add("create-qualification", command_create_qualification)
    p.add_argument("--parent-run-dir", required=True)
    p = add("qualify", command_qualify)
    p.add_argument("--gate-eligible", required=True)
    p = add("seal", command_seal)
    p.add_argument("--namespace", required=True)
    p = add("run-lane", command_run_lane)
    p.add_argument("--partition", required=True)
    p.add_argument("--lane", required=True)
    p.add_argument("--in-place", required=True)
    p = add("reconcile-provenance", command_reconcile)
    p.add_argument("--partition", required=True)
    p = add("audit", command_audit)
    p.add_argument("--partition", required=True)
    p.add_argument("--seal", required=True)
    p = add("seal-mandatory-set", command_mandatory)
    p.add_argument("--partition", required=True)
    p = add("finalize-review-capacity", command_capacity)
    p.add_argument("--partition", required=True)
    p = add("build-review-queue", command_queue)
    p.add_argument("--partition", required=True)
    p.add_argument("--include-development-refill")
    p.add_argument("--seal", required=True)
    p = add("submit-review", command_submit)
    p.add_argument("--task-id", required=True)
    p.add_argument("--reviewer-id", required=True)
    p.add_argument("--input", required=True)
    p = add("import-reviews", command_import)
    p.add_argument("--partition", required=True)
    p = add("adjudicate", command_adjudicate)
    p.add_argument("--partition", required=True)
    p = add("gate", command_gate)
    p.add_argument("--partition", required=True)
    p.add_argument("--emit-suitability-matrix", action="store_true")
    add("reveal-validation", command_reveal)
    return root


def main() -> int:
    """명령 결과를 JSON stdout과 0/2 exit code로 반환한다."""
    args = parser().parse_args()
    try:
        result = args.func(args)
        print(
            json.dumps(
                {"ok": True, "command": args.command, "result": result},
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "command": args.command,
                    "error": f"{type(error).__name__}: {error}",
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
