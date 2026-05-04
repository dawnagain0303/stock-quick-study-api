# stock-quick-study-api v2.5 sales breakdown history

수정 사항:
- 기존 주가/DART 재무/FnGuide 컨센서스/수주잔고 5개년 유지
- DART 최근 5개 사업보고서 원문에서 사업부문/제품별 매출액/매출비중 표 반복 파싱
- sales_breakdown.history 및 sales_breakdown.trend 추가
- 최신 매출구성은 기존 sales_breakdown.items에 유지

환경변수:
- DART_API_KEY
