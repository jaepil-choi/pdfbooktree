# AGENTS.md

이 문서는 `pdfbooktree` 저장소에서 AI 에이전트가 작업할 때 따라야 하는 운영 규칙이다.
규칙의 목적은 실험, 공개 인터페이스 검증, 실제 구현, 문서화, 커밋 흐름을 서로 분리해 작업 이력을 추적 가능하게 만드는 것이다.

## 1. 기본 원칙

- 이 저장소는 experiment driven development 방식으로 개발한다.
- 실험으로 먼저 가능성을 확인하고, 공개 인터페이스를 만든 뒤 showcase로 동작을 확인하며, `src/`와 `tests/` 변경은 별도 구현 노트로 설계 의도를 남긴다.
- 커밋은 사용자가 명시적으로 요청했을 때만 수행한다.
- 코드 실행은 항상 `uv run`을 사용한다.
- 작업을 마친 뒤 필요하면 `uv run pytest` 또는 `uv run ruff check` 같은 검증 명령을 실행한다.
- 코드 주석과 문서는 모두 한글로 작성한다.

## 2. 디렉터리 역할

| 경로 | 역할 | 테스트/구현 노트 필요 여부 |
| --- | --- | --- |
| `experiments/` | 단일 파일 PoC 실험을 보관한다. | 필요 없음 |
| `experiments/outputs/` | 실험 결과 파일을 저장한다. Git에 포함하지 않는다. | 필요 없음 |
| `experiments/experiments.json` | 실험 실행 기록과 결과 요약을 저장한다. | 필요 없음 |
| `showcase/` | 공개 인터페이스가 실제로 작동하는지 보여주는 실행 예제를 보관한다. | 필요 없음 |
| `showcase/showcase.json` | showcase 실행 기록과 결과 요약을 저장한다. | 필요 없음 |
| `src/` | 패키지 실제 구현 코드를 보관한다. | 필요 |
| `tests/` | 구현 검증 테스트를 보관한다. | 필요 |
| `docs/vibe/implementations/` | 구현 변경의 의사결정과 동작 방식을 기록한다. | 구현 노트 자체에는 추가 구현 노트 불필요 |
| `scripts/` | 개발 워크플로를 돕는 스크립트를 보관한다. | 보통 필요 없음 |

## 3. 실험 규칙

- 실험 파일은 `experiments/` 아래에 만든다.
- 파일명은 `001_설명.py`, `002_설명.py`처럼 세 자리 번호와 짧은 설명을 사용한다.
- 실험 파일은 monolithic script로 작성한다.
- 실험 단계에서는 재사용 가능한 패키지 구조를 먼저 만들지 않는다.
- 실험 결과 파일은 모두 `experiments/outputs/` 아래에 저장한다.
- `experiments/outputs/`는 Git에 포함하지 않는다.
- 실험 결과와 판단은 `experiments/experiments.json`에 기록한다.
- 실험 관련 커밋 메시지는 `exp:` 태그로 시작한다.
- 실험 변경에는 별도 `tests/` 테스트를 만들지 않는다.
- 실험 변경에는 implementation note를 만들지 않는다.

## 4. Showcase 규칙

- 공개 인터페이스를 만든 뒤 실제 사용 흐름을 확인하기 위해 `showcase/` 아래에 showcase 파일을 만든다.
- 파일명은 `001_설명.py`, `002_설명.py`처럼 세 자리 번호와 짧은 설명을 사용한다.
- showcase는 public interface가 예상대로 동작하는지 확인하는 용도다.
- showcase는 항상 real data와 live call로 실제 작동을 보여줘야 한다.
- showcase에서 synthetic data, mock data, stub call, hardcoded in-memory fake input만으로 성공을 증명하지 않는다.
- showcase 입력은 가능하면 `experiments/experiments.json`에 기록된 실제 데이터와 실험 결과를 참고해 고른다.
- 실제 데이터가 로컬에 없어서 showcase를 실행할 수 없으면 가짜 데이터로 대체하지 말고 blocked/failed 사유를 기록한다.
- showcase 실행 결과와 판단은 `showcase/showcase.json`에 기록한다.
- showcase 결과 파일이 필요하면 `showcase/outputs/` 같은 별도 output 디렉터리를 사용하고 Git 포함 여부를 명확히 관리한다.
- showcase 변경에는 별도 `tests/` 테스트를 만들지 않는다.
- showcase 변경에는 implementation note를 만들지 않는다.
- showcase 관련 커밋 메시지는 `showcase:` 태그로 시작한다.
- showcase는 별도 브랜치를 만들지 않고, public interface를 테스트해야 하는 `feat/` 또는 `fix/` 브랜치에서 작성한다.

## 5. 구현 규칙

- `src/`를 변경하면 구현 변경으로 간주한다.
- `tests/`를 변경하면 구현 변경으로 간주한다.
- 구현 변경은 가능한 한 실험에서 검증된 내용을 패키지 코드로 옮기는 방식으로 진행한다.
- 구현 변경 후에는 필요에 따라 `uv run pytest`, `uv run ruff check`, `uv run ruff format --check` 등을 실행한다.
- 구현 변경 커밋 뒤에는 반드시 implementation note를 작성한다.
- implementation note는 해당 구현 커밋에서 왜 그런 결정을 내렸는지, 어떻게 작동하는지, 어떤 대안을 배제했는지에 집중한다.
- implementation note는 `docs/vibe/implementations/001_{commit_id}.md` 형식으로 생성한다.

## 6. Implementation Note 생성 흐름

`src/` 또는 `tests/` 작업을 커밋할 때의 흐름은 다음과 같다.

1. `src/` 또는 `tests/` 변경을 완료한다.
2. 필요한 검증 명령을 실행한다.
3. 사용자가 명시적으로 커밋을 요청하면 구현 변경을 커밋한다.
4. 구현 변경 커밋 직후 `scripts/create-implementation-note.ps1`을 실행한다.
5. 스크립트는 last commit id를 확인해 `docs/vibe/implementations/001_{commit_id}.md` 형태의 파일을 생성한다.
6. 생성된 md 파일에 구현 결정, 작동 방식, 검증 내용, 남은 리스크를 작성한다.
7. implementation note만 별도 커밋한다.
8. implementation note 커밋 메시지는 `docs: write impl note for xxx` 형식을 사용한다.

## 7. 커밋 규칙

- AI 에이전트는 사용자가 명시적으로 요청하기 전까지 커밋하지 않는다.
- 커밋 요청이 없으면 변경 사항만 만들고 최종 응답에서 변경 파일과 검증 결과를 보고한다.
- `src/` 또는 `tests/` 구현 커밋은 implementation note 커밋과 분리한다.
- `docs/`, `experiments/`, `showcase/` 변경은 implementation note를 만들지 않는다.
- 실험 커밋 메시지는 `exp:`로 시작한다.
- showcase 커밋 메시지는 `showcase:`로 시작한다.
- 문서 전용 커밋 메시지는 필요에 따라 `docs:`로 시작한다.
- 구현 노트 커밋 메시지는 `docs: write impl note for xxx` 형식을 따른다.

## 8. 브랜치 규칙

- `develop` 브랜치는 개발 브랜치다.
- `master` 브랜치는 release 브랜치다.
- `develop`에서 새 기능을 만들 때는 `feat/설명` 브랜치를 만든다.
- `develop`에서 버그를 고칠 때는 `fix/설명` 브랜치를 만든다.
- 실험은 `exp/설명` 브랜치에서 진행한다.
- showcase만을 위한 별도 브랜치는 만들지 않는다.
- showcase는 해당 public interface를 만들거나 고치는 `feat/` 또는 `fix/` 브랜치에서 함께 작성한다.
- 작업 브랜치는 최종적으로 `develop`에 붙이는 것을 기본 흐름으로 한다.

## 9. 실행과 검증 규칙

- 이 저장소에서는 샌드박스 실행이 항상 차단되므로, AI 에이전트는 커맨드를 샌드박스로 먼저 시도하지 말고 항상 권한 상승으로 실행한다.
- Python 코드 실행은 `uv run python ...` 형식을 사용한다.
- 테스트 실행은 `uv run pytest`를 사용한다.
- Ruff lint는 `uv run ruff check`를 사용한다.
- Ruff format 검증은 `uv run ruff format --check`를 사용한다.
- 필요할 때만 검증을 실행하되, `src/` 또는 `tests/` 변경은 가능한 한 테스트나 lint로 확인한다.
- 단순 문서 변경에는 테스트나 lint를 강제하지 않는다.

## 10. 작업 유형별 체크리스트

### 10.1 실험 작업

- [ ] `exp/설명` 브랜치인지 확인한다.
- [ ] `experiments/NNN_설명.py` 파일을 만든다.
- [ ] monolithic script로 PoC를 작성한다.
- [ ] output은 `experiments/outputs/` 아래에 저장한다.
- [ ] 결과를 `experiments/experiments.json`에 기록한다.
- [ ] 테스트와 implementation note는 만들지 않는다.
- [ ] 커밋 요청이 있으면 `exp:` 태그로 커밋한다.

### 10.2 Showcase 작업

- [ ] `feat/` 또는 `fix/` 브랜치에서 진행 중인지 확인한다.
- [ ] `showcase/NNN_설명.py` 파일을 만든다.
- [ ] real data와 live call로 public interface 호출 흐름을 보여준다.
- [ ] synthetic/mock/stub 입력만으로 showcase 성공을 주장하지 않는다.
- [ ] 결과를 `showcase/showcase.json`에 기록한다.
- [ ] 테스트와 implementation note는 만들지 않는다.
- [ ] 커밋 요청이 있으면 `showcase:` 태그로 커밋한다.

### 10.3 구현 작업

- [ ] `feat/설명` 또는 `fix/설명` 브랜치인지 확인한다.
- [ ] 변경 범위를 `src/`와 `tests/` 중심으로 유지한다.
- [ ] 필요한 검증 명령을 `uv run`으로 실행한다.
- [ ] 사용자가 커밋을 요청할 때까지 커밋하지 않는다.
- [ ] 구현 커밋 후 `scripts/create-implementation-note.ps1`을 실행한다.
- [ ] 생성된 implementation note를 작성한다.
- [ ] implementation note를 별도 `docs:` 커밋으로 남긴다.

## 11. AI 에이전트 주의사항

- 사용자가 커밋하라고 명시하지 않았으면 절대 자동 커밋하지 않는다.
- 사용자가 브랜치를 만들라고 명시하지 않았으면 현재 작업 흐름에 맞는 브랜치 필요성을 먼저 확인한다.
- 기존 사용자 변경을 되돌리지 않는다.
- 실험 코드를 너무 일찍 `src/`로 옮기지 않는다.
- `src/`와 `tests/` 변경은 구현 노트가 필요하다는 점을 항상 기억한다.
- 문서와 주석은 한글로 작성한다.
- 명령 예시는 PowerShell 환경을 기준으로 작성한다.
