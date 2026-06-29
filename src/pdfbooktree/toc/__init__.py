"""TOC page 탐지와 TOC item parsing 패키지다.

구성 원칙:
- `detect`는 bookmark 없이 동작하는 ML 기반 runtime TOC page detector를 담는다.
- `detect_from_bookmarks`는 기존 bookmark를 기준 신호로 사용하는 보조 detector를 담는다.
- `features`와 `segments`는 두 detector가 공유할 수 있는 TOC page 판단 재료를 담는다.
- `parse`는 탐지된 TOC page에서 chapter/section item을 추출한다.
- `dataset_training`은 runtime detector가 반드시 사용하는 classifier 학습 흐름을 담는다.
- metric 계산은 이 패키지에 두지 않고 `pdfbooktree.metrics`에 둔다.
"""
