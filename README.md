# stock-quick-study-api v1.4 fnguide robust

수정 사항:
- CompanyGuide/FnGuide 컨센서스 파싱 개선
- 모든 table을 스캔해 Financial Highlight 후보를 찾음
- E 표시가 없으면 현재연도 이후 컬럼을 추정치 후보로 분류
- debug_summary 추가

환경변수:
- DART_API_KEY
