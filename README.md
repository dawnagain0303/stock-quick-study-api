# stock-quick-study-api v2.8 dcinside only

수정 사항:
- v2.7 뉴스 기능 유지
- 커뮤니티 수집은 네이버 종목토론실 제외
- 디시인사이드 검색만 사용
- 디시 검색 URL 패턴을 여러 개 시도해 수집 성공률 개선
- 단, 디시 차단/구조변경 시 100% 보장은 불가능

환경변수:
- DART_API_KEY
- NAVER_CLIENT_ID (선택, 네이버 뉴스 검색 API용)
- NAVER_CLIENT_SECRET (선택, 네이버 뉴스 검색 API용)
