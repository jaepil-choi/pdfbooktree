# 구현 노트: feat: add versioned OCR event contract

## 메타데이터

- 구현 커밋: `a9649efeabcf`
- 전체 커밋 ID: `a9649efeabcf3232e942e3334e57f1d41e5703fa`
- 커밋 일시: `2026-07-16T11:10:33+09:00`
- 노트 생성 일시: `2026-07-16 11:10:46 +09:00`

## 변경 배경

- OCR 진행 로그의 plain과 JSON 모드가 stdout을 사용해 최종 JSON 결과와 섞일 수 있었다. 에이전트가 stdout 전체를 단일 결과로 파싱하려면 진행 이벤트와 최종 결과의 스트림을 분리해야 했다.
- Phase 3A와 3B에서 확정한 결과 envelope와 종료 코드 계약을 장시간 실행되는 `ocr-overlay`에도 적용할 필요가 있었다.

## 결정 내용

- `CommandEventEnvelope`와 독립적인 `CLI_EVENT_SCHEMA_VERSION = 1`을 추가했다. 이벤트는 `schema_version`, `command`, `event`, `level`, `message`, `data` 필드를 갖는다.
- `ocr-overlay --format json`의 최종 결과는 stdout에 `CommandResultEnvelope` 한 줄로 출력하고, JSONL·plain·tqdm 진행 정보는 stderr에만 출력한다.
- 기존 `ocr_log.jsonl`과 `ocr_progress.json` 파일 형식은 바꾸지 않았다. 터미널 JSONL만 versioned event envelope로 감싸 artifact 소비자의 호환성을 유지했다.
- `--debug`를 추가하고 입력 오류 2, 실행 오류 1, 처리 실패 3이라는 기존 공통 종료 코드 계약을 적용했다.

## 작동 방식

- `JsonStderrOcrLogger`는 기존 `OcrLogEvent`에서 공통 이벤트 필드를 envelope 상단으로 옮기고 OCR 진행 값은 `data`에 담아 stderr JSONL로 직렬화한다.
- `PlainTextOcrLogger`와 `TqdmOcrLogger`도 stderr를 명시적으로 사용한다. 특히 tqdm 실패 메시지가 기본 stdout으로 빠지지 않도록 동일한 출력 스트림을 전달한다.
- `ocr-overlay`는 옵션을 검증하고 builder를 실행한 뒤 결과 요약을 `emit_command_result()`에 전달한다. 잘못된 page 범위, 없는 입력·cache, 기존 출력, bookmark overwrite 미확인은 `invalid_input`으로 분류한다.
- JSON 형식의 성공 시 stdout에는 최종 결과 한 줄만 남고 stderr의 각 줄은 독립적인 event JSON 객체가 된다.

## 검증

- `uv run pytest tests/test_ocr_logger.py tests/test_ocr_cli.py -q`: 16개 통과.
- `uv run pytest -q`: 204개 통과.
- `uv run ruff check src tests`: 통과.
- `uv run ruff format --check src tests`: 100개 파일 통과.
- `uv run pdfbooktree ocr-overlay --help`: `--format`과 `--debug` 노출을 확인했다.
- 실제 OCR provider live call은 외부 API 비용과 credential 의존성이 있어 실행하지 않았고, builder와 logger 경계를 사용한 계약 테스트로 스트림과 종료 코드를 검증했다.

## 대안과 제외한 선택지

- 파일용 `ocr_log.jsonl`까지 새 envelope로 변경하는 방안은 기존 `inspect ocr`와 artifact 소비자 호환성을 깨므로 제외했다.
- 최종 결과와 이벤트를 모두 stdout JSONL로 출력하는 방안은 stdout 전체를 단일 결과로 파싱할 수 없게 하므로 제외했다.
- `ocr-overlay-batch`, `classify-scan`, 기존 `batch`의 최종 결과 계약은 한 턴 범위를 넘기므로 이번 변경에 포함하지 않았다.

## 남은 리스크

- OCR batch가 공유 logger를 통해 내보내는 개별 overlay 이벤트는 아직 `ocr-overlay` command로 표시된다. batch 자체의 이벤트와 최종 결과 계약을 도입할 때 command context를 분리해야 한다.
- 분류 logger는 별도 구현이므로 아직 stdout 진행 로그와 최종 결과가 섞일 수 있다.
- Typer가 command 함수 호출 전에 처리하는 필수 옵션 누락이나 타입 변환 오류는 공통 JSON 오류 envelope가 아니다.
