# stock-quick-study-api v1.2

수정 사항:
- 현재가 중복 파싱 오류 수정: 네이버 일별시세 최신 종가 기준 사용
- DART corp_code 고정값 오류 가능성 제거: OpenDART corpCode.xml을 가볍게 파싱해 종목명 매칭
- pandas/lxml/matplotlib 미사용
- DART 재무제표 계정명 매칭 확대

환경변수:
- DART_API_KEY
