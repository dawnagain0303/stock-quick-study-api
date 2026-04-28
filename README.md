# stock-quick-study-api

개인 스터디용 한국 주식 퀵 리포트 API입니다.

## Render 환경변수

Render > Environment 에서 아래 값을 추가하세요.

- `DART_API_KEY` : OpenDART에서 발급받은 API 키

## 테스트 주소

배포 후 아래 주소를 열어보세요.

- `/health`
- `/stock-report?name=삼천당제약`

## 주의

- 네이버증권/뉴스/디시 검색은 개인 스터디용 참고 데이터입니다.
- DART 데이터는 회사별 계정명 차이 때문에 일부 항목이 `확인 불가`로 표시될 수 있습니다.
