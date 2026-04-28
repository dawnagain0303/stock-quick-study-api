import os
import io
import zipfile
import datetime as dt
from typing import Dict, Any, List, Optional

import requests
import pandas as pd
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

DART_API_KEY = os.getenv("DART_API_KEY", "")

app = FastAPI(title="Korean Stock Quick Study API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 personal stock study bot"
}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "message": "stock-quick-study-api is running",
        "dart_key_loaded": bool(DART_API_KEY)
    }


def get_dart_corp_list() -> pd.DataFrame:
    if not DART_API_KEY:
        return pd.DataFrame()
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    r = requests.get(url, params={"crtfc_key": DART_API_KEY}, timeout=20)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    xml = z.read("CORPCODE.xml")
    df = pd.read_xml(io.BytesIO(xml))
    df = df.dropna(subset=["stock_code"])
    df["stock_code"] = df["stock_code"].astype(str).str.zfill(6)
    return df


def resolve_stock(name: str) -> Dict[str, Optional[str]]:
    try:
        df = get_dart_corp_list()
        if df.empty:
            return {"name": name, "corp_code": None, "stock_code": None, "error": "DART API 키 없음 또는 corp list 조회 실패"}
        exact = df[df["corp_name"] == name]
        if exact.empty:
            contains = df[df["corp_name"].str.contains(name, na=False)]
            row = contains.iloc[0] if not contains.empty else None
        else:
            row = exact.iloc[0]
        if row is None:
            return {"name": name, "corp_code": None, "stock_code": None, "error": "종목명 매칭 실패"}
        return {
            "name": str(row["corp_name"]),
            "corp_code": str(row["corp_code"]).zfill(8),
            "stock_code": str(row["stock_code"]).zfill(6),
            "error": None
        }
    except Exception as e:
        return {"name": name, "corp_code": None, "stock_code": None, "error": str(e)}


def fetch_naver_price(stock_code: str) -> Dict[str, Any]:
    result = {
        "previous_close": None,
        "market_cap": None,
        "shares_outstanding": None,
        "source": f"https://finance.naver.com/item/main.naver?code={stock_code}",
        "note": "네이버증권 화면 기준. 개인 스터디용 참고."
    }
    try:
        url = result["source"]
        html = requests.get(url, headers=HEADERS, timeout=15).text
        soup = BeautifulSoup(html, "html.parser")

        # 전일 종가
        no_today = soup.select_one("p.no_today")
        if no_today:
            price_text = no_today.get_text("", strip=True).replace(",", "")
            if price_text.isdigit():
                result["previous_close"] = int(price_text)

        # 시총 / 상장주식수
        for th in soup.select("th"):
            label = th.get_text(" ", strip=True)
            td = th.find_next_sibling("td")
            if not td:
                continue
            val = td.get_text(" ", strip=True)
            if "시가총액" in label:
                result["market_cap_text"] = val
            if "상장주식수" in label:
                result["shares_outstanding_text"] = val
                digits = "".join(ch for ch in val if ch.isdigit())
                if digits:
                    result["shares_outstanding"] = int(digits)

        if result.get("previous_close") and result.get("shares_outstanding"):
            result["market_cap"] = result["previous_close"] * result["shares_outstanding"]

    except Exception as e:
        result["error"] = str(e)
    return result


def fetch_naver_daily_prices(stock_code: str, pages: int = 20) -> List[Dict[str, Any]]:
    rows = []
    for page in range(1, pages + 1):
        try:
            url = f"https://finance.naver.com/item/sise_day.naver?code={stock_code}&page={page}"
            html = requests.get(url, headers=HEADERS, timeout=10).text
            dfs = pd.read_html(io.StringIO(html))
            if not dfs:
                continue
            df = dfs[0].dropna()
            for _, r in df.iterrows():
                rows.append({
                    "date": str(r["날짜"]),
                    "close": int(str(r["종가"]).replace(",", "")),
                    "volume": int(str(r["거래량"]).replace(",", ""))
                })
        except Exception:
            continue
    return rows


def make_weekly_summary(stock_code: str) -> Dict[str, Any]:
    data = fetch_naver_daily_prices(stock_code, pages=25)
    if not data:
        return {"weekly": [], "note": "주가 데이터 확인 불가"}
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    cutoff = pd.Timestamp.today() - pd.Timedelta(days=370)
    df = df[df["date"] >= cutoff]
    weekly = df.set_index("date").resample("W-FRI").agg({"close": "last", "volume": "sum"}).dropna()
    if weekly.empty:
        return {"weekly": [], "note": "주봉 변환 실패"}

    return {
        "one_year_high": int(weekly["close"].max()),
        "one_year_low": int(weekly["close"].min()),
        "latest_weekly_close": int(weekly["close"].iloc[-1]),
        "weekly": [
            {"date": idx.strftime("%Y-%m-%d"), "close": int(row["close"])}
            for idx, row in weekly.tail(52).iterrows()
        ],
        "note": "네이버 일별시세를 주봉으로 변환"
    }


def dart_financials(corp_code: str, years: int = 5) -> List[Dict[str, Any]]:
    if not DART_API_KEY or not corp_code:
        return []
    current_year = dt.datetime.now().year
    out = []
    # 최근 사업보고서 기준: 전년도부터 역산
    for year in range(current_year - 1, current_year - years - 1, -1):
        try:
            url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
            params = {
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": "11011",  # 사업보고서
                "fs_div": "CFS"
            }
            js = requests.get(url, params=params, timeout=20).json()
            if js.get("status") != "000":
                params["fs_div"] = "OFS"
                js = requests.get(url, params=params, timeout=20).json()

            items = js.get("list", [])
            row = {"year": year, "revenue": None, "operating_income": None,
                   "net_income": None, "assets": None, "liabilities": None, "equity": None}
            for it in items:
                account = it.get("account_nm", "")
                amount = it.get("thstrm_amount", "").replace(",", "")
                if not amount or not amount.replace("-", "").isdigit():
                    continue
                amount = int(amount)

                if account in ["매출액", "수익(매출액)", "영업수익"]:
                    row["revenue"] = row["revenue"] or amount
                elif account in ["영업이익", "영업이익(손실)"]:
                    row["operating_income"] = row["operating_income"] or amount
                elif account in ["당기순이익", "당기순이익(손실)", "분기순이익", "반기순이익"]:
                    row["net_income"] = row["net_income"] or amount
                elif account == "자산총계":
                    row["assets"] = amount
                elif account == "부채총계":
                    row["liabilities"] = amount
                elif account == "자본총계":
                    row["equity"] = amount

            if row["revenue"] and row["operating_income"] is not None:
                row["operating_margin"] = round(row["operating_income"] / row["revenue"] * 100, 1)
            out.append(row)
        except Exception as e:
            out.append({"year": year, "error": str(e)})
    return list(reversed(out))


def dart_latest_regular_report_summary(corp_code: str) -> Dict[str, Any]:
    # 간단 버전: 최신 연도/분기 재무제표 API를 순차 조회
    if not DART_API_KEY or not corp_code:
        return {"note": "DART API 키 또는 corp_code 없음"}

    today = dt.datetime.now()
    candidates = []
    for year in [today.year, today.year - 1]:
        for reprt_code, label in [("11013", "1분기보고서"), ("11012", "반기보고서"), ("11014", "3분기보고서"), ("11011", "사업보고서")]:
            candidates.append((year, reprt_code, label))

    # 최신성이 높은 순서로 재정렬
    order = {"11014": 1, "11012": 2, "11013": 3, "11011": 4}
    candidates = sorted(candidates, key=lambda x: (x[0], -order.get(x[1], 9)), reverse=True)

    for year, reprt_code, label in candidates:
        try:
            url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
            params = {
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": reprt_code,
                "fs_div": "CFS"
            }
            js = requests.get(url, params=params, timeout=20).json()
            if js.get("status") != "000":
                params["fs_div"] = "OFS"
                js = requests.get(url, params=params, timeout=20).json()
            if js.get("status") != "000":
                continue

            row = {
                "year": year, "report_type": label, "reprt_code": reprt_code,
                "cash_and_cash_equivalents": None,
                "liabilities": None,
                "equity": None,
                "debt_ratio": None,
                "order_backlog": "확인 불가 - 1차 버전에서는 정기보고서 텍스트 파싱 필요"
            }
            for it in js.get("list", []):
                account = it.get("account_nm", "")
                amount = it.get("thstrm_amount", "").replace(",", "")
                if not amount or not amount.replace("-", "").isdigit():
                    continue
                amount = int(amount)
                if account in ["현금및현금성자산", "현금 및 현금성자산"]:
                    row["cash_and_cash_equivalents"] = row["cash_and_cash_equivalents"] or amount
                elif account == "부채총계":
                    row["liabilities"] = amount
                elif account == "자본총계":
                    row["equity"] = amount
            if row["liabilities"] is not None and row["equity"]:
                row["debt_ratio"] = round(row["liabilities"] / row["equity"] * 100, 1)
            return row
        except Exception:
            continue
    return {"note": "최신 정기보고서 재무 데이터 확인 불가"}


def naver_news_links(name: str, max_items: int = 5) -> List[Dict[str, str]]:
    try:
        query = requests.utils.quote(name)
        url = f"https://search.naver.com/search.naver?where=news&query={query}"
        html = requests.get(url, headers=HEADERS, timeout=15).text
        soup = BeautifulSoup(html, "html.parser")
        items = []
        for a in soup.select("a.news_tit")[:max_items]:
            items.append({"title": a.get("title") or a.get_text(strip=True), "url": a.get("href")})
        return items
    except Exception as e:
        return [{"error": str(e)}]


def dcinside_search_links(name: str, max_items: int = 5) -> List[Dict[str, str]]:
    try:
        query = requests.utils.quote(name)
        # 디시 통합 검색: 접속 제한이 있을 수 있음
        url = f"https://search.dcinside.com/post/q/{query}/sort/latest"
        html = requests.get(url, headers=HEADERS, timeout=15).text
        soup = BeautifulSoup(html, "html.parser")
        items = []
        for a in soup.select("a")[:80]:
            title = a.get_text(" ", strip=True)
            href = a.get("href", "")
            if name in title and "dcinside.com" in href:
                items.append({"title": title[:120], "url": href})
            if len(items) >= max_items:
                break
        if not items:
            return [{"note": "디시 검색 결과 확인 불가 또는 차단 가능"}]
        return items
    except Exception as e:
        return [{"error": str(e)}]


@app.get("/stock-report")
def stock_report(name: str = Query(..., description="종목명 예: 삼천당제약")):
    resolved = resolve_stock(name)
    stock_code = resolved.get("stock_code")
    corp_code = resolved.get("corp_code")

    if not stock_code:
        return {
            "input": name,
            "error": "종목코드 확인 실패",
            "resolved": resolved
        }

    price = fetch_naver_price(stock_code)
    weekly = make_weekly_summary(stock_code)
    financials = dart_financials(corp_code)
    latest = dart_latest_regular_report_summary(corp_code)
    news = naver_news_links(resolved["name"])
    community = dcinside_search_links(resolved["name"])

    return {
        "input": name,
        "resolved": resolved,
        "data 기준": {
            "price_market_cap": "네이버증권 전일 종가 기준",
            "historical_financials": "DART 사업보고서 기준",
            "cash_debt_ratio_order_backlog": "DART 최신 정기보고서 기준",
            "consensus": "네이버증권 기준 - 1차 버전에서는 추후 보완",
            "community": "디시인사이드 검색 결과 기준, 사실 검증 필요"
        },
        "price": price,
        "weekly_price_summary": weekly,
        "historical_financials": financials,
        "latest_regular_report": latest,
        "consensus": {
            "status": "추후 보완",
            "note": "네이버증권 컨센서스 표는 종목별 노출 구조가 달라 2차 버전에서 추가 권장"
        },
        "recent_news": news,
        "dcinside_community_links": community,
        "report_prompt_for_gpt": "위 JSON을 바탕으로 1페이지 한국 주식 퀵 스터디 리포트를 작성하세요. 불확실한 항목은 확인 불가로 표시하고, 매수/매도 추천은 하지 마세요."
    }
