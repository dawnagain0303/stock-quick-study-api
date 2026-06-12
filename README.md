# stock-quick-study-api v3.3 dcinside neostock 7d 60p

수정 사항:
- v3.2 기능 유지
- 디시인사이드 주식 갤러리(id=neostock) 수집 기간은 최근 7일 유지
- 페이지 순회 범위를 15페이지 -> 60페이지로 확대
- max_items 15개 -> 30개로 확대
- 오래된 날짜가 나오면 조기 중단
- 전체 디시 수집 시간 예산 18초 추가
- 디시 수집 실패/시간초과 시 전체 API가 죽지 않고 community_reaction만 확인 불가 처리

주의:
- 주식갤러리 글 회전이 매우 빠르면 60페이지도 7일 전체를 보장하지는 않음
- 디시 공식 API가 아니므로 차단/구조변경 가능성 있음

환경변수:
- DART_API_KEY
- NAVER_CLIENT_ID (선택)
- NAVER_CLIENT_SECRET (선택)
