"""파이프라인 결과를 채점하는 metric 패키지다.

역할:
- detector, parser, aligner가 만든 결과를 기준 결과와 비교하는 순수 계산을 담는다.
- 제품 처리 흐름과 평가 리포트 생성 흐름이 같은 metric 함수를 재사용할 수 있게 한다.

책임 밖:
- PDF를 열거나 bookmark를 추출하는 I/O 작업은 하지 않는다.
- TOC page를 직접 탐지하거나 bookmark를 생성하지 않는다.
"""
