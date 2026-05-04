# stock-quick-study-api v2.2 order backlog columnfix

수정 사항:
- 수주잔고 표에서 '당기말 수주잔(YYYY.MM.DD)' 컬럼을 backlog로 정확히 인식
- 기존에는 '당기/기말' 키워드 때문에 period로 잘못 잡히던 문제 수정
- order_backlog.backlog_best_candidate 및 items[].backlog 반환 개선

환경변수:
- DART_API_KEY
