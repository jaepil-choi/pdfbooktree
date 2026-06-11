"""TOC page segment 후보를 다루는 모듈의 자리다.

역할:
- page 단위 feature나 점수에서 연속된 TOC 후보 구간을 만든다.
- 단일 page 점수와 구간 점수를 분리해 관리한다.
- 최종 detector가 여러 candidate segment 중 하나를 고를 수 있는 자료 구조를 제공한다.

책임 밖:
- PDF text에서 feature를 계산하는 일은 `toc.features`가 담당한다.
- 기존 bookmark를 기준 신호로 써서 TOC page를 찾는 일은
  `toc.detect_from_bookmarks`가 담당한다.
- detector 결과를 정답 후보와 비교하는 metric 계산은 `metrics.toc_pages`가 담당한다.

구현 메모:
- 다음 구현 단계에서 실험 003의 contiguous window mass와 runtime-safe scoring을
  이 파일로 옮긴다.
- 모든 page number는 package 규칙에 맞춰 1-based로 유지한다.
"""
