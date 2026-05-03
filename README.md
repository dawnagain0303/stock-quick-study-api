# stock-quick-study-api v1.9 fnguide encoding lines

수정 사항:
- FnGuide 한글 깨짐 방지를 위해 utf-8 강제 디코딩
- Financial Highlight 연간 블록에서 행명 다음에 숫자가 한 줄씩 나오는 구조 대응
- 매출액/영업이익/순이익/EPS/PER/PBR 등 행명 다음 n개 숫자를 연도 순서로 매칭

환경변수:
- DART_API_KEY
