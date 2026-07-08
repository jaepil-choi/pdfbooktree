---
name: experiment-log-lookup
description: pdfbooktree 저장소의 experiments/experiments.json과 showcase/showcase.json을 전체 파일 읽기 없이 조회한다. 두 로그가 각각 수백 KB, 수천 줄로 자라서 파일을 통째로 Read하면 컨텍스트를 낭비하고 원하는 항목을 찾기 어렵다. 과거 실험/showcase 결과를 확인하거나("017번 실험 뭐였지", "font_size clamp 관련 실험 찾아줘", "지난 showcase에서 offset 어떻게 나왔지"), 새 실험을 시작하기 전에 관련 선행 실험이 있는지 확인하거나, experiments.json/showcase.json에 새 항목을 추가하기 전에 기존 id 목록을 확인할 때 반드시 이 skill을 사용하라. experiments.json이나 showcase.json 파일을 Read tool로 직접 열기 전에 먼저 이 skill의 list/search로 범위를 좁혀라.
---

# Experiment Log Lookup

`experiments/experiments.json`과 `showcase/showcase.json`은 AGENTS.md가 정한 append-only 실행 기록이다.
항목 수가 늘어날수록(현재 experiments 69개, ~5100줄) 파일 전체를 Read하면 컨텍스트만 소비하고
정작 필요한 항목은 못 찾기 쉽다. 이 skill은 `scripts/query_log.py`로 필요한 항목만 골라 읽는다.

**중요: 이 스크립트는 조회 전용이다.** experiments.json/showcase.json에 새 항목을 추가하거나 수정하는
로직은 포함하지 않는다. 새 실험/showcase 기록을 남기는 것은 AGENTS.md 3~4절의 기존 워크플로를 그대로 따르고,
이 skill은 그 워크플로를 시작하기 전 "이미 비슷한 실험이 있었나?"를 확인하거나, 끝난 뒤 "그 실험 결과가 뭐였지?"를
찾아볼 때만 쓴다.

## 언제 쓰나

- 사용자가 특정 실험 번호나 주제를 언급하며 결과를 물어볼 때 (예: "038번 실험 findings 보여줘", "font_size clamp 실험 뭐 있었지")
- 새 실험을 설계하기 전에 관련 선행 실험이 있는지 확인할 때
- experiments.json/showcase.json에 새 id를 추가하기 전, 번호 충돌을 피하려고 기존 id 목록을 훑을 때
- showcase 결과(예: offset 추정값, TOC range)를 다시 확인하고 싶을 때

`experiments/experiments.json`이나 `showcase/showcase.json`을 Read tool로 직접 열려는 충동이 들면,
먼저 이 skill의 `list` 또는 `search`로 후보를 좁힌 뒤 `get`으로 필요한 항목만 펼쳐라.

## 사용법

모든 명령은 저장소 어디서 실행하든 동작한다(스크립트가 자기 위치 기준으로 repo root를 찾는다).
PowerShell 기준 예시:

```powershell
# 1. 전체 id + 한 줄 요약만 훑어본다 (기본은 experiments 로그)
uv run python .claude/skills/experiment-log-lookup/scripts/query_log.py list

# showcase 로그를 보려면 --log showcase
uv run python .claude/skills/experiment-log-lookup/scripts/query_log.py list --log showcase

# 2. id(전체 또는 숫자 접두사)로 항목 전체를 펼친다
uv run python .claude/skills/experiment-log-lookup/scripts/query_log.py get 038
uv run python .claude/skills/experiment-log-lookup/scripts/query_log.py get 038_full_flow_toc_to_bookmark

# 3. 키워드로 id/purpose/finding을 검색한다 (매칭된 항목의 id + 스니펫만 반환)
uv run python .claude/skills/experiment-log-lookup/scripts/query_log.py search "font_size"
uv run python .claude/skills/experiment-log-lookup/scripts/query_log.py search "offset" --log showcase
uv run python .claude/skills/experiment-log-lookup/scripts/query_log.py search "keyword" --log both
```

### 명령 정리

| 명령 | 동작 | 출력 |
| --- | --- | --- |
| `list` | 모든 항목의 id + purpose 한 줄 요약(100자 제한) | 인덱스 (전체 항목보다 훨씬 짧다) |
| `get <query>` | id 정확히 일치 → 숫자 접두사 일치 → 부분 문자열 일치 순으로 매칭 | 일치 항목 1개의 전체 JSON. 여러 개 걸리면 후보 목록만 보여주고 더 구체적인 id를 요구한다 |
| `search <keyword>` | id/purpose/finding에서 대소문자 무시 부분 문자열 검색(`--field`로 범위 좁힘 가능) | 매칭된 id + 어느 필드에서 걸렸는지 + 앞뒤 문맥 스니펫 |

`--log`는 `experiments`(기본값) / `showcase` / `both` 중 선택하며, 서브커맨드 뒤에 붙인다.

### 흐름 예시

1. 사용자가 "font_size clamp 관련 이전 실험 있었나?"라고 물으면 → `search "font_size"`로 후보 id를 얻는다.
2. 후보 중 `070_ocr_overlay_font_size_clamp_check`가 관련 있어 보이면 → `get 070`으로 그 항목만 전체 출력한다.
3. 이 두 단계만으로 5100줄짜리 파일을 통째로 읽지 않고 필요한 finding에 도달한다.

## 스키마 차이 주의

- `experiments.json`의 top-level 배열 키는 `"experiments"`, `showcase.json`은 `"showcases"`다. 스크립트가 이 차이를
  자동으로 처리하므로 신경 쓸 필요 없다.
- 항목마다 공통 필드(`id`, `purpose`, `inputs`, `outputs`, `finding`, `ran_at`)에 더해 실험별로 `model`,
  `temperature`, `source_experiment(s)`, `books`, `manual_review_cases` 같은 추가 필드가 붙기도 한다. `get`은
  해당 항목의 모든 필드를 그대로 보여주므로 별도 대응이 필요 없다.
