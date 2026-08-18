# pdfbooktree

[English](https://github.com/jaepil-choi/pdfbooktree/blob/master/README.en.md) ·
[문서](https://github.com/jaepil-choi/pdfbooktree/blob/master/docs/reference.md) ·
[변경 기록](https://github.com/jaepil-choi/pdfbooktree/blob/master/CHANGELOG.md)

`pdfbooktree`는 PDF 책을 읽어 계층형 bookmark를 추론하는 Python 도구다. 목차
페이지를 찾아 파싱하는 대신, 책 전체의 글자 크기와 페이지 배치(typography와
geometry)를 근거로 장·절 구조를 복원한다. 결과는 탐색 가능한 bookmark PDF와,
LLM이 절 단위로 나눠 읽을 수 있는 Markdown 디렉터리 트리로 저장된다.

## 핵심 기능

- typography·geometry 기반 bookmark 구조 추론 (TOC 페이지 불필요)
- 북마크가 삽입된 PDF 생성
- 절 단위로 나뉜 Markdown 디렉터리 트리 내보내기
- 스캔 PDF를 위한 OCR 텍스트 레이어 오버레이
- 여러 권을 한 번에 처리하는 batch 실행
- 중간 결과를 확인하는 read-only inspection 명령

## AI agent를 위한 도구

이 패키지는 사람만큼 AI agent를 염두에 두고 설계됐다. Agent는 책 전체를
읽는 대신, 저렴하고 결정론적인 추출을 먼저 실행하고, 나온 구조가 말이
되는지 inspection 명령으로 확인한 뒤, 책마다 파라미터를 조정해 다시
실행한다.

## 설치

```powershell
uv add pdfbooktree
```

스캔 PDF에 실시간 OCR 오버레이가 필요하면 `[ocr]` extra를 함께 설치한다.

```powershell
uv add "pdfbooktree[ocr]"
```

## 시작하기

프로젝트에서 다음 명령 한 번으로 skill을 설치한다. agents 규격 도구와 Claude
양쪽에 동일한 skill이 등록된다.

```powershell
pdfbooktree skill install
```

이후 사용법과 명령, 옵션, 산출물 구조는 설치된 skill과 그 참조 문서가
안내한다. 제거는 `pdfbooktree skill uninstall`로 한다.

## 알아둘 것

- 추론 결과는 **목차 초안**이다. 자동으로 완성된 정답이 아니라 사람이나
  agent가 검토하고 조정하는 것을 전제로 한다. 계획을 먼저 만들고(`infer`)
  확인한 뒤 적용하는(`apply`) 흐름을 쓰면 반영 전에 손볼 수 있다.
- OCR 오버레이는 외부 문서 파싱 서비스를 호출하므로 **API 키**가 필요하다.
  키가 없으면 이미 text layer가 있는 PDF만 처리할 수 있다.
- **암호 입력**이 필요한 PDF는 지원하지 않는다. 미리 암호를 푼 사본을 쓰라.
- 원본 PDF는 기본적으로 덮어쓰지 않는다.

## 라이선스

[MIT License](https://github.com/jaepil-choi/pdfbooktree/blob/master/LICENSE)
