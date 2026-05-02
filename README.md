# stock-quick-study-api v1.7 fnguide row

수정 사항:
- FnGuide Financial Highlight 연간 컨센서스 파싱 개선
- 연도 헤더를 먼저 추출하고, 각 tr의 td 숫자값을 행 이름 기준으로 직접 매칭
- 매출액/영업이익/당기순이익/지배주주순이익/EPS/BPS/PER/PBR/ROE 지원
- debug_rows_sample 추가

환경변수:
- DART_API_KEY
