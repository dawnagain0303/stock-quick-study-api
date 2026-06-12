# stock-quick-study-api v3.1 action compat

수정 사항:
- v3.0 기능 유지
- GPT Action 호환성 보강
- 기존 GET /stock-report?name=종목명 유지
- 추가 GET /getStockReport?name=종목명 지원
- 추가 POST /getStockReport {"name":"종목명"} 지원
- OpenAPI recent_news 스키마를 실제 응답(object)에 맞게 수정
- 예외 발생 시 status=failed JSON 반환

환경변수:
- DART_API_KEY
- NAVER_CLIENT_ID (선택)
- NAVER_CLIENT_SECRET (선택)
