"""TOC page range 탐지 결과를 채점하는 metric 모듈의 자리다.

역할:
- 예측 TOC page range와 기준 TOC page range의 segment IoU를 계산한다.
- start/end page error, missing/extra page, page precision/recall 같은 값을 계산한다.
- 기본 detector와 bookmark 기반 detector의 결과를 비교할 때 쓰는 순수 함수를 제공한다.

책임 밖:
- TOC page range를 직접 탐지하지 않는다.
- 기존 bookmark에서 기준 range를 복원하지 않는다.
- 평가 report 파일 저장이나 batch orchestration은 별도 상위 모듈에서 담당한다.

구현 메모:
- 다음 구현 단계에서 작은 list[int] 입력만 받는 순수 함수부터 채운다.
- 모든 page number는 package 규칙에 맞춰 1-based로 해석한다.
"""
