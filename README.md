# stock-quick-study-api v3.5 naver news blog

수정 사항:
- 디시인사이드 수집 제거
- 메인 /stock-report 안정성 우선
- 네이버 뉴스 30일 recent_news 유지
- 네이버 블로그 30일 blog_reaction 추가
- /blog-reaction?name=종목명 별도 조회 지원
- GET/POST /getStockReport 호환 유지
- 큰 raw/debug 필드 제거 유지

필요 환경변수:
- DART_API_KEY
- NAVER_CLIENT_ID
- NAVER_CLIENT_SECRET

참고:
- NAVER_CLIENT_ID / NAVER_CLIENT_SECRET이 없으면 blog_reaction은 확인 불가 또는 빈 결과로 표시됩니다.
