# 변경 기록

이 프로젝트는 [Semantic Versioning](https://semver.org/)을 따른다.

## Unreleased

- GitHub Actions의 Windows/Linux matrix를 원격에서 실제 확인한 뒤 릴리스한다.
- CI의 Rich ANSI help 출력에서도 `--version` 공개 option 계약을 안정적으로
  검증한다.
- 공개 결과 직렬화용 `to_jsonable()`, `to_json()`과 `JsonValue` 계약을 추가했다.
- root와 공개 subpackage의 `__all__`을 지원 API surface로 명시하고, Python API
  reference를 README·PyPI metadata·설치 가능한 project skill에 연결했다.
- v0.1.0의 OCR provider가 Upstage Document Parse 전용임을 명시했다.

## 0.1.0

### 추가

- typography 기반 bookmark 추론, 기존 outline 재사용과 단계형
  `infer → inspect → apply` workflow.
- 계층형 bookmark PDF와 YAML front matter·wiki navigation을 갖춘 Markdown graph.
- Upstage Document Parse 기반 비파괴 OCR overlay와 scan/OCR batch 분류.
- immutable run/batch manifest, JSON CLI envelope, review summary/item evidence.
- `apply --dry-run`, process/infer progress event, batch include/exclude glob.
- `__version__`, `package_version()`, PEP 561 `py.typed`와 typed artifact 경로.
- `process_pdf()`, `infer_pdf()`, `preview_apply_plan()`, `apply_plan_file()` 고수준
  immutable Python workflow.
- 모든 process/infer/apply run의 canonical `bookmark_plan.json` snapshot.

### 의존성

- `httpx`, `pikepdf`, `python-dotenv`를 `pdfbooktree[ocr]` extra로 분리했다.
- `tqdm`은 일반 처리에서도 사용하는 core dependency로 유지한다.
- OCR extra가 없으면 help와 batch dry-run은 동작하고 live overlay만 안정된
  `OptionalDependencyError`로 실패한다.

### 안전성

- OCR input/output 동일 경로를 거부하고 sibling temporary PDF를 atomic replace한다.
- recursive batch가 output subtree와 대문자 `.PDF`를 안전하게 처리한다.
- 실패 결과가 존재하지 않는 output 경로를 성공 artifact처럼 반환하지 않는다.
- PDF 본문의 `[[...]]` 문자열을 생성된 wiki link로 오인하지 않는다.
