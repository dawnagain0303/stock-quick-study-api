# stock-quick-study-api v1.5 fnguide highlight

수정 사항:
- CompanyGuide Financial Highlight 연간표(div id=highlight_D_A) 직접 파싱
- 실패 시 highlight 영역/전체 테이블 보조 스캔
- annual_estimates에 향후 추정치(E) 컬럼 반환
- debug_summary에 highlight_D_A 탐지 여부 표시

환경변수:
- DART_API_KEY
