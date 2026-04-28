# stock-quick-study-api

가벼운 2차 수정본입니다.

## 바뀐 점
- pandas 제거
- lxml 제거
- matplotlib 제거
- DART 전체 기업코드 XML 파싱 제거
- 우선 주요 테스트 종목은 고정 매핑으로 처리

## Render 환경변수
- DART_API_KEY

## 테스트
- /health
- /stock-report?name=삼성전자
- /stock-report?name=삼천당제약
