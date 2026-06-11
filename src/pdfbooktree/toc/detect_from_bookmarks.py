"""기존 PDF bookmark를 기준 신호로 사용해 TOC page range를 찾는 모듈의 자리다.

역할:
- bookmark title 목록과 앞부분 page text를 함께 사용해 TOC page range를 복원한다.
- bookmark가 있는 PDF에서 detector 검증용 기준 결과를 만들 때 사용한다.
- bookmark title matching, anchor page 관찰, page text와 bookmark title의 overlap 같은
  bookmark-guided 신호를 이 파일에 모은다.

책임 밖:
- bookmark 없이 feature만으로 TOC page를 찾는 기본 처리 경로는 `toc.detect`가 담당한다.
- 기존 bookmark 자체를 추출하고 clean 여부를 판단하는 일은 `pdf.bookmarks`가 담당한다.
- 결과 간 IoU나 page precision/recall 계산은 `metrics.toc_pages`가 담당한다.

명명 결정:
- `from_bookmarks`는 입력 계약을 직접 드러낸다.
- 이 모듈은 bookmark가 있을 때만 의미가 있다.
"""
