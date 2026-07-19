# 기여 가이드

[English](CONTRIBUTING.en.md)

## 개발 환경

Python 3.12 이상과 `uv`가 필요하다. CI는 Python 3.12, 3.13, 3.14를 Windows와
Linux에서 검증한다.

```powershell
uv sync --locked --dev --python 3.12
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

모든 Python 실행은 `uv run`을 사용한다. 코드 주석과 내부 저장소 문서는 한글로
작성한다. README, CLI, Python API, artifact, 기여, 보안, 변경 기록 같은 공개
문서는 한국어와 영어의 대응 범위를 함께 유지한다.

## 변경 흐름

1. 새 가설은 `experiments/NNN_설명.py`의 단일 PoC로 먼저 검증하고 결과를
   `experiments/experiments.json`에 기록한다.
2. 공개 인터페이스는 `src/`와 `tests/`에 구현한다.
3. 실제 데이터와 live public interface는 `showcase/NNN_설명.py`에서 확인하고
   `showcase/showcase.json`에 기록한다. mock이나 synthetic 입력만으로 showcase
   성공을 주장하지 않는다.
4. CLI/API가 바뀌면 repo-local `use-pdfbooktree` skill, package bundled skill과
   README를 함께 갱신한다.
5. 관련 테스트와 전체 lint/format check를 실행한다.

기존 사용자 변경을 되돌리지 않는다. 커밋은 요청된 경우에만 만들며 `src/` 또는
`tests/` 구현 커밋 뒤에는 저장소 규칙에 따라 별도 implementation note를 작성한다.

## Pull request 확인 사항

- 입력·출력 경로와 overwrite 실패 시 데이터 보존을 검증했는가?
- 공개 page 번호가 모두 1-based인가?
- JSON stdout, progress stderr와 exit code 계약을 유지하는가?
- Windows/Linux 파일명, YAML과 wiki relation이 결정적인가?
- 새 기능의 Python API, CLI, skill reference와 실제 데이터 showcase가 일치하는가?
