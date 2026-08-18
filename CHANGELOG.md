# 변경 기록

[English](CHANGELOG.en.md)

이 프로젝트는 [Semantic Versioning](https://semver.org/)을 따른다.

## Unreleased

### 추가

- 생성된 Markdown tree를 진단하는 `inspect markdown` 명령과 `inspect_markdown_tree()`,
  `inspect_compare_markdown()`. verdict와 원인, 실행 가능한 재시도 후보를 함께 낸다.
- `inspect compare`가 bookmark plan JSON과 Markdown manifest를 자동으로 구분한다.
- typography를 한 번만 분석하고 heading knob 조합을 메모리 안에서 재평가하는
  `inspect sweep` 명령과 `inspect_heading_sweep()`. `process` output artifact를
  만들지 않으므로 agent가 값을 바꿀 때마다 재실행하지 않고도 조합별
  candidate 수와 방향(`increases_candidates`/`decreases_candidates`/`mixed`/
  `no_effect`)을 저렴하게 확인할 수 있다.
- 책 내부 상대값으로 정의한 typography knob `max_headings_per_page`,
  `size_class_depth`. 둘 다 기본값 `0`(비활성화)이라 기존 동작을 바꾸지
  않는다. OCR overlay는 각 줄의 font size를 bbox에서 정하고 책마다 다른
  값에서 clamp하므로, 절대 font size나 tier 번호는 책 사이에서 뜻이
  달라져 agent가 쓸 수 있는 축이 아니다. 두 knob은 책 내부에서만 뜻이
  통하는 상대 축(page당 희소성, 상위 size class 개수)으로 이 문제를
  피한다.
- `skill install`이 이제 두 target을 설치한다. `.agents/skills/`에는 전체
  지침을, `.claude/skills/`에는 이 저장소의 `CLAUDE.md`가 `AGENTS.md`에
  위임하는 것과 같은 adapter 한 파일을 설치하며, 두 target 모두 같은
  번들 원본에서 파생돼 workflow 목록 같은 내용을 손으로 중복 유지하지
  않는다.

### 변경

- 구조가 깨진 기존 outline은 재사용하지 않고 그 사유를 warning과 review summary에 남긴다.
- 추론 plan의 level jump를 연속된 depth로 정규화한다.
- strict geometry 후보가 없을 때만 기존 heading evidence를 page당 하나 사용한다.

### 수정

- typography tier 구성에서 density peak와 cut 개수가 어긋나 IndexError가 나던 문제.
- `max_headings_per_page`가 `heading_candidate_mode=position`에서는 최종
  선택에 전혀 반영되지 않던 문제. font 후보 집합에만 상한이 걸려 있었는데
  `position` mode는 그 집합을 쓰지 않아 값을 바꿔도 plan이 조용히
  그대로였다. 이제 mode 분기 뒤 최종 선택 집합에 상한을 적용한다.

### 제거

- 소비자가 없던 `typography.min_tier_gap` config key. 이제 이 key를 주면
  조용히 무시하지 않고 `invalid_config`로 거절한다.
- 항상 `raw_tier_count`와 같은 값이던 `TierSet.gap_merged_tier_count` 필드와
  `font_size_tiers.json`, `height_tiers.json` artifact의 동일 항목.
- 중복이던 height tier 증거. OCR overlay에서는 font size와 bounding-box
  height가 같은 측정값이라(최상위 tier가 표본 전체에서 100% 동일), 독립
  증거 두 개로 취급하던 것을 제거하고 font tier만 남겼다.

## 0.1.1 - 2026-07-19

### 문서

- 프로젝트 소개와 README를 짧고 자연스러운 사용 안내로 다시 썼다.
- 공개 문서에서 내부 평가 데이터, 커밋 식별자와 showcase 기록을 제거했다.
- 내부 검토 문서는 `develop`에만 두고 공개 `master` 릴리스에서는 제외한다.

## 0.1.0 - 2026-07-19

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
- 공개 결과 직렬화용 `to_jsonable()`, `to_json()`과 `JsonValue` 계약.
- root와 공개 subpackage의 `__all__` 지원 API surface, 한·영 Python API·CLI·artifact
  reference와 설치 가능한 project skill.

### 배포

- Windows/Linux와 Python 3.12/3.13/3.14 test 및 동일 wheel clean-install smoke.
- plain Click help로 80열에서도 긴 option 이름과 `--version`을 온전히 표시.
- sdist/wheel 단일 build, `twine check`, SHA-256 checksum과 provenance attestation.
- GitHub protected environment와 OIDC Trusted Publishing 기반 TestPyPI/PyPI workflow.

### 의존성

- `httpx`, `pikepdf`, `python-dotenv`를 `pdfbooktree[ocr]` extra로 분리했다.
- `tqdm`은 일반 처리에서도 사용하는 core dependency로 유지한다.
- OCR extra가 없으면 help와 batch dry-run은 동작하고 live overlay만 안정된
  `OptionalDependencyError`로 실패한다.

### 안전성과 문서

- OCR input/output 동일 경로를 거부하고 sibling temporary PDF를 atomic replace한다.
- recursive batch가 output subtree와 대문자 `.PDF`를 안전하게 처리한다.
- 실패 결과가 존재하지 않는 output 경로를 성공 artifact처럼 반환하지 않는다.
- PDF 본문의 `[[...]]` 문자열을 생성된 wiki link로 오인하지 않는다.
- 자동 생성 목차의 검토 필요성, OCR 외부 전송과 비용, 암호화 PDF와 복잡한
  문서 구조의 제한을 한국어와 영어로 안내한다.
- v0.1.0의 OCR provider가 Upstage Document Parse 전용임을 명시한다.
