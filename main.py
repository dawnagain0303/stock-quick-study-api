import os
import re
import io
import datetime as dt
import xml.etree.ElementTree as ET
import zipfile
from typing import Dict, Any, List, Optional

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

DART_API_KEY = os.getenv("DART_API_KEY", "")

app = FastAPI(title="Korean Stock Quick Study API", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {"User-Agent": "Mozilla/5.0 personal stock study bot"}

# 1차 안정화용 고정 매핑. 필요한 종목은 여기에 계속 추가 가능.
STOCKS = {
    "삼성전자": {"corp_code": "00126380", "stock_code": "005930"},
    "삼천당제약": {"corp_code": "00130724", "stock_code": "000250"},
    "동진쎄미켐": {"corp_code": "00132618", "stock_code": "005290"},
    "한화비전": {"corp_code": "00159226", "stock_code": "489790"},
    "파두": {"corp_code": "01598773", "stock_code": "440110"},
    "롯데케미칼": {"corp_code": "00106106", "stock_code": "011170"},
    "SK하이닉스": {"corp_code": "00164779", "stock_code": "000660"},
    "현대차": {"corp_code": "00164742", "stock_code": "005380"},
    "알테오젠": {"corp_code": "00631518", "stock_code": "196170"},
    "셀트리온": {"corp_code": "00413046", "stock_code": "068270"},
}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "message": "stock-quick-study-api is running",
        "dart_key_loaded": bool(DART_API_KEY),
        "version": "light-1.1"
    }


def safe_int(text: str) -> Optional[int]:
    if text is None:
        return None
    cleaned = re.sub(r"[^0-9\-]", "", str(text))
    if cleaned in ("", "-"):
        return None
    try:
        return int(cleaned)
    except Exception:
        return None


def resolve_stock(name: str) -> Dict[str, Any]:
    name = name.strip()
    if name in STOCKS:
        return {"name": name, **STOCKS[name], "matched_by": "fixed_map"}
    # 부분 일치
    for k, v in STOCKS.items():
        if name in k or k in name:
            return {"name": k, **v, "matched_by": "fixed_map_partial"}
    return {
        "name": name,
        "corp_code": None,
        "stock_code": None,
        "error": "아직 고정 매핑에 없는 종목입니다. main.py의 STOCKS에 종목코드/corp_code를 추가해야 합니다."
    }


def fetch_naver_price(stock_code: str) -> Dict[str, Any]:
    url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
    result = {
        "source": url,
        "previous_close": None,
        "market_cap": None,
        "shares_outstanding": None,
        "note": "네이버증권 화면 기준 개인 스터디용 참고"
    }
    try:
        html = requests.get(url, headers=HEADERS, timeout=10).text
        soup = BeautifulSoup(html, "html.parser")

        no_today = soup.select_one("p.no_today")
        if no_today:
            result["previous_close"] = safe_int(no_today.get_text("", strip=True))

        text = soup.get_text(" ", strip=True)
        # 상장주식수: 네이버 화면에서 '상장주식수 5,969,782,550' 형태 탐색
        m = re.search(r"상장주식수\s*([0-9,]+)", text)
        if m:
            result["shares_outstanding"] = safe_int(m.group(1))

        if result["previous_close"] and result["shares_outstanding"]:
            result["market_cap"] = result["previous_close"] * result["shares_outstanding"]

        # 시총 텍스트도 보조 저장
        m2 = re.search(r"시가총액\s*([0-9,]+)\s*억원", text)
        if m2:
            result["market_cap_text"] = m2.group(1) + "억원"

    except Exception as e:
        result["error"] = str(e)
    return result


def fetch_naver_daily_prices(stock_code: str, pages: int = 15) -> List[Dict[str, Any]]:
    rows = []
    for page in range(1, pages + 1):
        url = f"https://finance.naver.com/item/sise_day.naver?code={stock_code}&page={page}"
        try:
            html = requests.get(url, headers=HEADERS, timeout=8).text
            soup = BeautifulSoup(html, "html.parser")
            for tr in soup.select("tr"):
                tds = [td.get_text(" ", strip=True) for td in tr.select("td")]
                if len(tds) >= 7 and re.match(r"\d{4}\.\d{2}\.\d{2}", tds[0]):
                    rows.append({
                        "date": tds[0].replace(".", "-"),
                        "close": safe_int(tds[1]),
                        "volume": safe_int(tds[6])
                    })
        except Exception:
            continue
    return [r for r in rows if r.get("date") and r.get("close")]


def weekly_summary(stock_code: str) -> Dict[str, Any]:
    daily = fetch_naver_daily_prices(stock_code, pages=25)
    if not daily:
        return {"note": "네이버 일별시세 확인 불가", "weekly": []}

    # 주별 마지막 거래일 종가 추출
    parsed = []
    for r in daily:
        try:
            d = dt.datetime.strptime(r["date"], "%Y-%m-%d").date()
            parsed.append((d, r["close"]))
        except Exception:
            pass
    parsed = sorted(parsed)
    cutoff = dt.date.today() - dt.timedelta(days=370)
    parsed = [(d, c) for d, c in parsed if d >= cutoff]
    weeks = {}
    for d, c in parsed:
        year_week = d.isocalendar()[:2]
        weeks[year_week] = (d, c)

    weekly = [{"date": v[0].isoformat(), "close": v[1]} for _, v in sorted(weeks.items())][-52:]
    closes = [x["close"] for x in weekly]
    return {
        "one_year_high": max(closes) if closes else None,
        "one_year_low": min(closes) if closes else None,
        "latest_weekly_close": closes[-1] if closes else None,
        "weekly": weekly,
        "note": "네이버 일별시세를 간이 주봉으로 변환"
    }


def dart_single_account_all(corp_code: str, year: int, report_code: str, fs_div: str = "CFS") -> List[Dict[str, Any]]:
    if not DART_API_KEY:
        return []
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": report_code,
        "fs_div": fs_div
    }
    js = requests.get(url, params=params, timeout=12).json()
    if js.get("status") != "000":
        return []
    return js.get("list", [])


def amount_from_item(item: Dict[str, Any]) -> Optional[int]:
    return safe_int(item.get("thstrm_amount"))


def historical_financials(corp_code: str) -> List[Dict[str, Any]]:
    if not corp_code:
        return []
    current = dt.date.today().year
    out = []
    for year in range(current - 5, current):
        items = dart_single_account_all(corp_code, year, "11011", "CFS")
        if not items:
            items = dart_single_account_all(corp_code, year, "11011", "OFS")
        row = {
            "year": year,
            "revenue": None,
            "operating_income": None,
            "net_income": None,
            "assets": None,
            "liabilities": None,
            "equity": None,
            "operating_margin": None
        }
        for it in items:
            acc = it.get("account_nm", "")
            amt = amount_from_item(it)
            if amt is None:
                continue
            if acc in ["매출액", "수익(매출액)", "영업수익"]:
                if row["revenue"] is None:
                    row["revenue"] = amt
            elif acc in ["영업이익", "영업이익(손실)"]:
                if row["operating_income"] is None:
                    row["operating_income"] = amt
            elif acc in ["당기순이익", "당기순이익(손실)"]:
                if row["net_income"] is None:
                    row["net_income"] = amt
            elif acc == "자산총계":
                row["assets"] = amt
            elif acc == "부채총계":
                row["liabilities"] = amt
            elif acc == "자본총계":
                row["equity"] = amt
        if row["revenue"] and row["operating_income"] is not None:
            row["operating_margin"] = round(row["operating_income"] / row["revenue"] * 100, 1)
        out.append(row)
    return out


def latest_regular_report(corp_code: str) -> Dict[str, Any]:
    if not corp_code:
        return {}
    y = dt.date.today().year
    # 최신 정기보고서 우선순위: 올해 3Q/반기/1Q, 전년 사업보고서
    candidates = [
        (y, "11014", "3분기보고서"),
        (y, "11012", "반기보고서"),
        (y, "11013", "1분기보고서"),
        (y - 1, "11011", "사업보고서"),
    ]
    for year, code, label in candidates:
        items = dart_single_account_all(corp_code, year, code, "CFS")
        if not items:
            items = dart_single_account_all(corp_code, year, code, "OFS")
        if not items:
            continue
        row = {
            "year": year,
            "report_type": label,
            "cash_and_cash_equivalents": None,
            "liabilities": None,
            "equity": None,
            "debt_ratio": None,
            "order_backlog": "확인 불가 - 수주잔고는 보고서 본문 파싱 2차 개발 필요"
        }
        for it in items:
            acc = it.get("account_nm", "")
            amt = amount_from_item(it)
            if amt is None:
                continue
            if acc in ["현금및현금성자산", "현금 및 현금성자산"]:
                if row["cash_and_cash_equivalents"] is None:
                    row["cash_and_cash_equivalents"] = amt
            elif acc == "부채총계":
                row["liabilities"] = amt
            elif acc == "자본총계":
                row["equity"] = amt
        if row["liabilities"] is not None and row["equity"]:
            row["debt_ratio"] = round(row["liabilities"] / row["equity"] * 100, 1)
        return row
    return {"note": "최신 정기보고서 재무 데이터 확인 불가"}


def naver_news(name: str, max_items: int = 5) -> List[Dict[str, str]]:
    try:
        q = requests.utils.quote(name)
        url = f"https://search.naver.com/search.naver?where=news&query={q}"
        html = requests.get(url, headers=HEADERS, timeout=8).text
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for a in soup.select("a.news_tit")[:max_items]:
            out.append({"title": a.get("title") or a.get_text(strip=True), "url": a.get("href")})
        return out or [{"note": "뉴스 검색 결과 확인 불가"}]
    except Exception as e:
        return [{"error": str(e)}]


def dcinside_links(name: str) -> List[Dict[str, str]]:
    # 1차 버전에서는 차단 가능성이 높아 링크만 제공
    q = requests.utils.quote(name)
    return [{
        "note": "디시인사이드 검색은 차단/구조변경 가능성이 있어 GPT가 참고 링크로 확인",
        "search_url": f"https://search.dcinside.com/post/q/{q}/sort/latest"
    }]


@app.get("/stock-report")
def stock_report(name: str = Query(..., description="종목명 예: 삼천당제약")):
    resolved = resolve_stock(name)
    if not resolved.get("stock_code"):
        return {"input": name, "resolved": resolved, "error": resolved.get("error")}

    stock_code = resolved["stock_code"]
    corp_code = resolved["corp_code"]

    return {
        "input": name,
        "resolved": resolved,
        "data_basis": {
            "price_market_cap": "네이버증권 전일 종가 기준",
            "historical_financials": "DART 사업보고서 기준",
            "cash_debt_ratio_order_backlog": "DART 최신 정기보고서 기준",
            "consensus": "네이버증권 기준 - 2차 개발 필요",
            "community": "디시인사이드 주식갤러리 검색 참고"
        },
        "price": fetch_naver_price(stock_code),
        "weekly_price_summary": weekly_summary(stock_code),
        "historical_financials": historical_financials(corp_code),
        "latest_regular_report": latest_regular_report(corp_code),
        "consensus": {
            "status": "2차 개발 필요",
            "note": "네이버증권 컨센서스 표 자동 추출은 다음 단계에서 추가"
        },
        "recent_news": naver_news(resolved["name"]),
        "dcinside_community": dcinside_links(resolved["name"]),
        "report_prompt_for_gpt": "위 JSON을 바탕으로 1페이지 한국 주식 퀵 스터디 리포트를 작성하세요. 불확실한 항목은 확인 불가로 표시하고, 매수/매도 추천은 하지 마세요."
    }
