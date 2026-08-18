---
name: use-pdfbooktree
description: 이 저장소의 pdfbooktree Python API와 CLI를 사용해 PDF 책을 조사하고, 스캔 여부를 분류하고, OCR
  text layer를 만들거나 재사용하고, 북마크 계획을 추론·검토·적용하고, 북마크 PDF와 계층형 또는 길이 제한 Markdown을 생성하며,
  디렉터리를 batch 처리하고, 설정·실행 manifest·artifact·계획 차이를 점검한다. Claude가 이 저장소에서 PDF 구조화,
  OCR overlay, 기존 outline 품질, bookmark plan, Markdown export, batch run, CLI 자동화 또는
  pdfbooktree Python 통합을 다룰 때 사용한다.
---

# pdfbooktree 사용 (Claude adapter)

이 파일은 이 저장소의 `CLAUDE.md`가 `AGENTS.md`에 위임하는 것과 같은 adapter다.
전체 지침 본문은 여기에 복제하지 않고 agents target(`../../../.agents/skills/use-pdfbooktree/SKILL.md`)을
그대로 가리킨다. 이 파일이 하는 일은 progressive disclosure의 첫 단계로, 사용
가능한 workflow를 요약해 Claude가 계속 읽을지 판단하게 하는 것뿐이다.

## 사용 가능한 workflow

1. 입력을 빠르게 파악하려면 읽기 전용 `inspect page-count`, `inspect text`, `inspect bookmarks`를 사용하라.
2. 디렉터리의 PDF를 선별하려면 `classify-scan`을 사용하라. 스캔 PDF이면서 의미 있는 bookmark가 없는 항목이 OCR batch target이다.
3. OCR batch에서 일정 길이 이상의 책만 대상으로 삼으려면 `--min-page-count N`을 사용하라. `page_count >= N`인 문서만 target이 되며, 실제 호출 전 확인에는 `--dry-run`을 함께 사용하라.
4. 추출 가능한 text가 없거나 부족하면 북마크 추론 전에 `ocr-overlay` 또는 `ocr-overlay-batch`를 별도 전처리로 실행하라. `ProcessingConfig.ocr_policy`는 현재 `never`만 지원하며 `auto|always`는 config validation에서 거부된다.
5. 빠른 최종 결과가 필요하면 CLI `process` 또는 Python `process_pdf()`를 사용하라.
6. 계획을 검토·수정·비교해야 하면 `infer` → `inspect plan`/`inspect compare` → `apply --dry-run` → `apply` 흐름을 사용하라.
7. 여러 PDF를 구조화하려면 `batch` 또는 `BatchProcessor.run()`을 사용하라.
8. `process` 또는 `apply`로 Markdown graph를 만든 뒤에는 `inspect markdown <OUTPUT_DIR>`으로 `verdict`와 `findings`를 확인하라. `verdict`가 `ok`가 아니면 결과가 제시하는 `retry[].command`로 재실행하고(재시도 후보일 뿐 보장이 아니다), `inspect compare <BEFORE_MANIFEST> <AFTER_MANIFEST>`로 재실행 전후 Markdown manifest를 비교해 실제로 개선됐는지 확인하라.
9. `inspect markdown`이나 `inspect plan`으로 훑어본 구조가 말이 안 되면(page당 heading이 너무 많거나 너무 적으면) `inspect sweep <PDF>`로 `typography.size_class_depth`, `typography.max_headings_per_page` 조합별 candidate 수 표를 한 번에 확인하라. 표에서 방향(`direction`)과 `plausible_settings`를 보고 값을 고른 뒤 `process --set typography.max_headings_per_page=<값>` 또는 `--set typography.size_class_depth=<값>`으로 재실행하고, `inspect markdown`으로 다시 확인하라. 두 knob 모두 기본값은 `0`(비활성화, 기존 동작 유지)이며 책마다 필요한 값이 달라 모든 책에 맞는 단일 정답 설정은 없다.
10. 결과를 기계적으로 소비하려면 `--format json`을 사용하고 exit code와 stderr를 함께 검사하라.

## 전체 지침과 레퍼런스

전체 원칙, outline 정책, OCR 규칙, 계획 검토, 설정, Python/CLI 선택 기준은
아래 agents target의 전체 `SKILL.md`에 있다. 이 adapter는 요약만 유지하므로
실제 작업 전에는 반드시 전체 본문을 읽으라.

- 전체 SKILL.md 본문: [../../../.agents/skills/use-pdfbooktree/SKILL.md](../../../.agents/skills/use-pdfbooktree/SKILL.md)
- [references/cli.en.md](../../../.agents/skills/use-pdfbooktree/references/cli.en.md)
- [references/cli.md](../../../.agents/skills/use-pdfbooktree/references/cli.md)
- [references/contracts.en.md](../../../.agents/skills/use-pdfbooktree/references/contracts.en.md)
- [references/contracts.md](../../../.agents/skills/use-pdfbooktree/references/contracts.md)
- [references/python-api.en.md](../../../.agents/skills/use-pdfbooktree/references/python-api.en.md)
- [references/python-api.md](../../../.agents/skills/use-pdfbooktree/references/python-api.md)
