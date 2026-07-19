# 보안 정책

[English](SECURITY.en.md)

## 지원 범위

보안 수정은 최신 공개 버전을 대상으로 제공한다. 아직 공개 릴리스가 없다면
`master`의 최신 릴리스 후보를 기준으로 조사한다.

## 비공개 제보

취약점, 임의 파일 overwrite, credential 노출 또는 악성 PDF 처리 문제는 공개
issue에 exploit 세부 정보를 올리지 않는다.

1. GitHub 저장소의 **Security → Report a vulnerability**에서 private security
   advisory를 연다.
2. 해당 기능을 사용할 수 없으면 `chljeffreyz@gmail.com`으로 재현 조건, 영향,
   영향을 받는 버전과 최소 PoC를 보낸다.

접수 확인 전에는 취약점 세부 정보나 실제 사용자 문서를 공개하지 않는다. OCR
provider API key와 원본 PDF 같은 민감 자료는 필요한 최소 범위만 공유한다.

live OCR은 page PNG를 외부 Upstage API에 전송한다. `.env`, raw OCR cache와 review
preview에는 credential 또는 민감한 원문이 포함될 수 있으므로 공개 issue나
재현용 archive에 첨부하지 않는다.
