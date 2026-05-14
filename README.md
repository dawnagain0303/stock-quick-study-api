# stock-quick-study-api v3.0 dcinside neostock 30d

수정 사항:
- v2.9 자본총계/수주잔고 검증 유지
- 디시 커뮤니티 수집 방식을 통합검색에서 주식 갤러리(id=neostock) 30일치 목록 순회 방식으로 변경
- 종목명/종목코드가 제목에 포함된 글을 sample_posts로 수집
- 실패 시 디시 통합검색 fallback 1회 시도
- 네이버 종목토론실은 사용하지 않음

환경변수:
- DART_API_KEY
- NAVER_CLIENT_ID (선택)
- NAVER_CLIENT_SECRET (선택)
