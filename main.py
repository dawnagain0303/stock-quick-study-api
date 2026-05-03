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

app = FastAPI(title="Korean Stock Quick Study API", version="1.9.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {"User-Agent": "Mozilla/5.0 personal stock study bot"}
_CORP_CACHE = None

FALLBACK_STOCKS = {
    "삼성전자": {"corp_code": "00126380", "stock_code": "005930"},
    "삼천당제약": {"corp_code": None, "stock_code": "000250"},
    "동진쎄미켐": {"corp_code": None, "stock_code": "005290"},
    "한화비전": {"corp_code": None, "stock_code": "489790"},
    "파두": {"corp_code": None, "stock_code": "440110"},
    "롯데케미칼": {"corp_code": None, "stock_code": "011170"},
    "SK하이닉스": {"corp_code": "00164779", "stock_code": "000660"},
    "현대차": {"corp_code": "00164742", "stock_code": "005380"},
    "알테오젠": {"corp_code": None, "stock_code": "196170"},
    "셀트리온": {"corp_code": "00413046", "stock_code": "068270"},
}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "message": "stock-quick-study-api is running",
        "dart_key_loaded": bool(DART_API_KEY),
        "version": "v1.9-fnguide-encoding-lines"
    }


def safe_number(text: Any) -> Optional[float]:
    if text is None:
        return None
    s = str(text).replace("\xa0", " ").strip()
    if s in ["", "-", "N/A", "nan"]:
        return None
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    cleaned = re.sub(r"[^0-9.\-]", "", s)
    if cleaned in ("", "-", "."):
        return None
    try:
        val = float(cleaned)
        if neg:
            val = -val
        return int(val) if val.is_integer() else val
    except Exception:
        return None


def safe_int(text: Any) -> Optional[int]:
    v = safe_number(text)
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


def load_dart_corp_list() -> List[Dict[str, str]]:
    global _CORP_CACHE
    if _CORP_CACHE is not None:
        return _CORP_CACHE
    if not DART_API_KEY:
        _CORP_CACHE = []
        return _CORP_CACHE
    try:
        url = "https://opendart.fss.or.kr/api/corpCode.xml"
        r = requests.get(url, params={"crtfc_key": DART_API_KEY}, timeout=20)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml_bytes = z.read("CORPCODE.xml")
        root = ET.fromstring(xml_bytes)
        rows = []
        for item in root.findall("list"):
            corp_name = item.findtext("corp_name")
            corp_code = item.findtext("corp_code")
            stock_code = item.findtext("stock_code")
            if stock_code and stock_code.strip():
                rows.append({
                    "corp_name": corp_name.strip(),
                    "corp_code": corp_code.strip().zfill(8),
                    "stock_code": stock_code.strip().zfill(6),
                })
        _CORP_CACHE = rows
        return rows
    except Exception:
        _CORP_CACHE = []
        return _CORP_CACHE


def resolve_stock(name: str) -> Dict[str, Any]:
    name = name.strip()
    rows = load_dart_corp_list()
    for r in rows:
        if r["corp_name"] == name:
            return {"name": r["corp_name"], "corp_code": r["corp_code"], "stock_code": r["stock_code"], "matched_by": "dart_exact"}
    for r in rows:
        if name in r["corp_name"] or r["corp_name"] in name:
            return {"name": r["corp_name"], "corp_code": r["corp_code"], "stock_code": r["stock_code"], "matched_by": "dart_partial"}
    if name in FALLBACK_STOCKS:
        return {"name": name, **FALLBACK_STOCKS[name], "matched_by": "fallback"}
    for k, v in FALLBACK_STOCKS.items():
        if name in k or k in name:
            return {"name": k, **v, "matched_by": "fallback_partial"}
    return {"name": name, "corp_code": None, "stock_code": None, "error": "종목명 매칭 실패"}


def fetch_naver_daily_prices(stock_code: str, pages: int = 25) -> List[Dict[str, Any]]:
    rows = []
    for page in range(1, pages + 1):
        url = f"https://finance.naver.com/item/sise_day.naver?code={stock_code}&page={page}"
        try:
            html = requests.get(url, headers=HEADERS, timeout=8).text
            soup = BeautifulSoup(html, "html.parser")
            for tr in soup.select("tr"):
                tds = [td.get_text(" ", strip=True) for td in tr.select("td")]
                if len(tds) >= 7 and re.match(r"\d{4}\.\d{2}\.\d{2}", tds[0]):
                    rows.append({"date": tds[0].replace(".", "-"), "close": safe_int(tds[1]), "volume": safe_int(tds[6])})
        except Exception:
            continue
    seen = set()
    clean = []
    for r in rows:
        if r.get("date") and r.get("close") and r["date"] not in seen:
            seen.add(r["date"])
            clean.append(r)
    return sorted(clean, key=lambda x: x["date"])


def fetch_naver_price(stock_code: str) -> Dict[str, Any]:
    url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
    result = {"source": url, "previous_close": None, "market_cap": None, "shares_outstanding": None, "note": "네이버증권 화면 및 일별시세 기준 개인 스터디용 참고"}
    try:
        daily = fetch_naver_daily_prices(stock_code, pages=1)
        if daily:
            latest = daily[-1]
            result["previous_close"] = latest["close"]
            result["price_date"] = latest["date"]

        html = requests.get(url, headers=HEADERS, timeout=10).text
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        m = re.search(r"상장주식수\s*([0-9,]+)", text)
        if m:
            result["shares_outstanding"] = safe_int(m.group(1))

        m2 = re.search(r"시가총액\s*([0-9,]+)\s*억원", text)
        if m2:
            result["market_cap_text"] = m2.group(1) + "억원"

        if result["previous_close"] and result["shares_outstanding"]:
            result["market_cap"] = result["previous_close"] * result["shares_outstanding"]
    except Exception as e:
        result["error"] = str(e)
    return result


def weekly_summary(stock_code: str) -> Dict[str, Any]:
    daily = fetch_naver_daily_prices(stock_code, pages=25)
    if not daily:
        return {"note": "네이버 일별시세 확인 불가", "weekly": []}
    parsed = []
    for r in daily:
        try:
            d = dt.datetime.strptime(r["date"], "%Y-%m-%d").date()
            parsed.append((d, r["close"]))
        except Exception:
            pass
    cutoff = dt.date.today() - dt.timedelta(days=370)
    parsed = [(d, c) for d, c in parsed if d >= cutoff]
    weeks = {}
    for d, c in parsed:
        year_week = d.isocalendar()[:2]
        weeks[year_week] = (d, c)
    weekly = [{"date": v[0].isoformat(), "close": v[1]} for _, v in sorted(weeks.items())][-52:]
    closes = [x["close"] for x in weekly]
    return {"one_year_high": max(closes) if closes else None, "one_year_low": min(closes) if closes else None, "latest_weekly_close": closes[-1] if closes else None, "weekly": weekly, "note": "네이버 일별시세를 간이 주봉으로 변환"}


def dart_single_account_all(corp_code: str, year: int, report_code: str, fs_div: str = "CFS") -> List[Dict[str, Any]]:
    if not DART_API_KEY or not corp_code:
        return []
    try:
        url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
        params = {"crtfc_key": DART_API_KEY, "corp_code": corp_code, "bsns_year": str(year), "reprt_code": report_code, "fs_div": fs_div}
        js = requests.get(url, params=params, timeout=12).json()
        if js.get("status") != "000":
            return []
        return js.get("list", [])
    except Exception:
        return []


def amount_from_item(item: Dict[str, Any]) -> Optional[int]:
    return safe_int(item.get("thstrm_amount"))


def pick_first(row: Dict[str, Any], key: str, amount: Any):
    if row.get(key) is None:
        row[key] = amount


def historical_financials(corp_code: str) -> List[Dict[str, Any]]:
    if not corp_code:
        return []
    current = dt.date.today().year
    out = []
    for year in range(current - 5, current):
        items = dart_single_account_all(corp_code, year, "11011", "CFS") or dart_single_account_all(corp_code, year, "11011", "OFS")
        row = {"year": year, "revenue": None, "operating_income": None, "net_income": None, "assets": None, "liabilities": None, "equity": None, "operating_margin": None, "dart_item_count": len(items)}
        for it in items:
            acc = it.get("account_nm", "").replace(" ", "")
            amt = amount_from_item(it)
            if amt is None:
                continue
            if acc in ["매출액", "수익(매출액)", "영업수익", "매출", "매출수익"]:
                pick_first(row, "revenue", amt)
            elif acc in ["영업이익", "영업이익(손실)", "영업손익"]:
                pick_first(row, "operating_income", amt)
            elif acc in ["당기순이익", "당기순이익(손실)", "연결당기순이익", "당기순손익"]:
                pick_first(row, "net_income", amt)
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
        return {"note": "corp_code 없음"}
    y = dt.date.today().year
    candidates = [(y, "11014", "3분기보고서"), (y, "11012", "반기보고서"), (y, "11013", "1분기보고서"), (y - 1, "11011", "사업보고서"), (y - 1, "11014", "3분기보고서"), (y - 1, "11012", "반기보고서"), (y - 1, "11013", "1분기보고서")]
    for year, code, label in candidates:
        items = dart_single_account_all(corp_code, year, code, "CFS") or dart_single_account_all(corp_code, year, code, "OFS")
        if not items:
            continue
        row = {"year": year, "report_type": label, "cash_and_cash_equivalents": None, "liabilities": None, "equity": None, "debt_ratio": None, "order_backlog": "확인 불가 - 수주잔고는 보고서 본문 파싱 2차 개발 필요", "dart_item_count": len(items)}
        for it in items:
            acc = it.get("account_nm", "").replace(" ", "")
            amt = amount_from_item(it)
            if amt is None:
                continue
            if acc in ["현금및현금성자산", "현금및현금성자산및단기금융상품", "현금"]:
                pick_first(row, "cash_and_cash_equivalents", amt)
            elif acc == "부채총계":
                row["liabilities"] = amt
            elif acc == "자본총계":
                row["equity"] = amt
        if row["liabilities"] is not None and row["equity"]:
            row["debt_ratio"] = round(row["liabilities"] / row["equity"] * 100, 1)
        return row
    return {"note": "최신 정기보고서 재무 데이터 확인 불가"}


def parse_table_number(text: str):
    return safe_number(text)


def fetch_fnguide_consensus(stock_code: str) -> Dict[str, Any]:
    """
    CompanyGuide Financial Highlight 연간 블록 파싱 v1.9.
    개선:
    - FnGuide 한글 깨짐 방지: 응답 bytes를 utf-8 우선 강제 디코딩
    - 값이 '한 줄에 여러 숫자'가 아니라 '다음 줄마다 숫자 1개'인 구조 대응
    - Financial Highlight > IFRS(연결) > Annual > 20xx(E) 블록에서 행명 뒤 숫자들을 순서대로 수집
    """
    gicode = "A" + stock_code
    url = f"https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode={gicode}&cID=&MenuYn=Y&ReportGB=&NewMenuID=101&stkGb=701"

    headers = {
        **HEADERS,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://finance.naver.com/",
        "Connection": "keep-alive",
    }

    metrics = [
        ("매출액", "revenue"),
        ("영업이익", "operating_income"),
        ("당기순이익", "net_income"),
        ("지배주주순이익", "controlling_net_income"),
        ("영업이익률", "operating_margin"),
        ("ROE", "roe"),
        ("EPS(원)", "eps"),
        ("BPS(원)", "bps"),
        ("PER", "per"),
        ("PBR", "pbr"),
        ("부채비율", "debt_ratio")
    ]
    metric_labels = [m[0] for m in metrics]

    def clean_line(s):
        return str(s or "").replace("\xa0", " ").strip()

    def norm(s):
        return re.sub(r"\s+", "", clean_line(s))

    def parse_single_number(line):
        txt = clean_line(line)
        if txt in ["", "-", "N/A"]:
            return None
        if re.fullmatch(r"N/A|\(?-?\d[\d,]*\.?\d*\)?", txt):
            return parse_table_number(txt)
        return None

    def extract_num_tokens(line):
        tokens = re.findall(r"N/A|\(?-?\d[\d,]*\.?\d*\)?", clean_line(line))
        return [parse_table_number(t) for t in tokens]

    def is_year_label(line):
        return bool(re.fullmatch(r"20\d{2}/\d{2}(?:\(E\))?", clean_line(line)))

    def extract_year_labels(lines):
        labels = []
        for ln in lines:
            if is_year_label(ln):
                lab = clean_line(ln)
                if lab not in labels:
                    labels.append(lab)
        return labels

    def make_year_records(labels):
        out = []
        for lab in labels:
            m = re.search(r"(20\d{2})", lab)
            if m:
                out.append({
                    "year": int(m.group(1)),
                    "label": lab,
                    "is_estimate": "E" in lab
                })
        return out

    def find_best_annual_block(lines):
        starts = [i for i, ln in enumerate(lines) if norm(ln) == "FinancialHighlight"]
        blocks = []
        for idx, s in enumerate(starts):
            e = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
            block = lines[s:e]
            txt = "\n".join(block)
            labels = extract_year_labels(block)
            estimate_count = sum(1 for x in labels if "E" in x)

            score = 0
            if "IFRS(연결)" in txt:
                score += 100
            if re.search(r"^Annual$", txt, re.MULTILINE):
                score += 100
            for yy, pts in [("2028/12(E)", 400), ("2027/12(E)", 300), ("2026/12(E)", 200), ("2025/12(E)", 100)]:
                if yy in txt:
                    score += pts
            if "Net Quarter" in txt:
                score -= 50
            if "매출액" in txt and "영업이익" in txt:
                score += 100
            score += estimate_count * 50 + len(labels)

            blocks.append({
                "start": s,
                "end": e,
                "score": score,
                "labels": labels,
                "estimate_count": estimate_count,
                "preview": block[:25]
            })

        if not blocks:
            return None
        blocks.sort(key=lambda x: x["score"], reverse=True)
        return blocks[0]

    def is_metric_line(line):
        nl = norm(line)
        for lab in metric_labels:
            if nl == norm(lab):
                return True
        for lab in ["매출액", "당기순이익", "지배주주순이익", "영업이익률", "부채비율"]:
            if norm(lab) in nl and len(nl) <= len(norm(lab)) + 8:
                return True
        return False

    def row_matches(line, metric_label):
        nl = norm(line)
        ml = norm(metric_label)
        if metric_label in ["EPS(원)", "BPS(원)"]:
            return nl == ml
        if metric_label in ["PER", "PBR", "ROE"]:
            return nl == metric_label
        if metric_label == "영업이익":
            return nl == "영업이익"
        return ml in nl and len(nl) <= len(ml) + 8

    def collect_values_after(block, start_idx, n):
        vals = []
        used_lines = []
        for j in range(start_idx + 1, min(start_idx + 80, len(block))):
            ln = block[j]

            if vals and is_metric_line(ln):
                break

            if is_year_label(ln) or "(E)" in ln or "Estimate" in ln or "컨센서스" in ln or "추정치" in ln:
                continue

            single = parse_single_number(ln)
            if single is not None:
                vals.append(single)
                used_lines.append(ln)
            else:
                many = extract_num_tokens(ln)
                if len(many) >= 2:
                    vals.extend(many)
                    used_lines.append(ln)

            if len(vals) >= n:
                return vals[:n], used_lines[:n]

        return vals[:n], used_lines

    def parse_block(lines, block_info):
        block = lines[block_info["start"]:block_info["end"]]
        labels = block_info["labels"]
        if len(labels) > 8:
            labels = labels[-8:]

        years = make_year_records(labels)
        if len(years) < 4:
            return None

        n = len(years)
        data = [dict(y) for y in years]
        matched = 0
        value_count = 0
        debug_rows = []

        for metric_label, key in metrics:
            for i, ln in enumerate(block):
                if not row_matches(ln, metric_label):
                    continue
                vals, used = collect_values_after(block, i, n)
                if len(vals) < n:
                    continue
                for idx, v in enumerate(vals):
                    data[idx][key] = v
                    if v is not None:
                        value_count += 1
                matched += 1
                debug_rows.append({
                    "metric": metric_label,
                    "key": key,
                    "line_index": i,
                    "values": vals,
                    "used_lines": used
                })
                break

        annual_all = data
        annual_estimates = [x for x in annual_all if x.get("is_estimate")]

        if matched == 0 or value_count == 0:
            return None

        return {
            "status": "ok" if annual_estimates else "no_estimate_columns_found",
            "source": url,
            "parser": "financial_highlight_line_values_v19",
            "unit_note": "CompanyGuide Financial Highlight 표 기준. 매출/영업이익/순이익은 억원, EPS/BPS는 원, PER/PBR은 배, ROE/영업이익률은 %",
            "annual_all": annual_all,
            "annual_estimates": annual_estimates,
            "matched_rows": matched,
            "value_count": value_count,
            "selected_block_score": block_info["score"],
            "selected_labels": labels,
            "debug_rows_sample": debug_rows[:10],
            "note": "개인 스터디용 참고. Financial Highlight 연간 블록에서 행명 다음 숫자줄을 순서대로 수집"
        }

    try:
        r = requests.get(url, headers=headers, timeout=15)
        try:
            html = r.content.decode("utf-8", errors="replace")
        except Exception:
            html = r.text

        soup = BeautifulSoup(html, "html.parser")
        lines = [clean_line(x) for x in soup.get_text("\n", strip=True).split("\n")]
        lines = [x for x in lines if x]

        block_info = find_best_annual_block(lines)

        debug = {
            "url": url,
            "html_len": len(html),
            "line_count": len(lines),
            "financial_highlight_blocks": len([x for x in lines if norm(x) == "FinancialHighlight"]),
            "best_block": block_info
        }

        if not block_info:
            return {
                "status": "확인 불가",
                "annual_all": [],
                "annual_estimates": [],
                "note": "Financial Highlight 블록을 찾지 못함",
                "debug": debug
            }

        parsed = parse_block(lines, block_info)
        if parsed:
            parsed["debug_summary"] = {
                "url": url,
                "line_count": len(lines),
                "selected_block_score": block_info["score"],
                "selected_labels": block_info["labels"],
                "selected_preview": block_info["preview"]
            }
            return parsed

        return {
            "status": "확인 불가",
            "annual_all": [],
            "annual_estimates": [],
            "note": "IFRS(연결) Annual 추정치 블록은 선택했으나 행명 다음 숫자줄 매칭 실패",
            "debug": debug
        }

    except Exception as e:
        return {
            "status": "확인 불가",
            "annual_all": [],
            "annual_estimates": [],
            "note": "CompanyGuide Financial Highlight 파싱 중 오류",
            "error": str(e)
        }

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
    q = requests.utils.quote(name)
    return [{"note": "디시인사이드 검색은 차단/구조변경 가능성이 있어 GPT가 참고 링크로 확인", "search_url": f"https://search.dcinside.com/post/q/{q}/sort/latest"}]


@app.get("/stock-report")
def stock_report(name: str = Query(..., description="종목명 예: 삼천당제약")):
    resolved = resolve_stock(name)
    if not resolved.get("stock_code"):
        return {"input": name, "resolved": resolved, "error": resolved.get("error")}
    stock_code = resolved["stock_code"]
    corp_code = resolved.get("corp_code")
    return {
        "input": name,
        "resolved": resolved,
        "data_basis": {
            "price_market_cap": "네이버증권 일별시세 최신 종가 기준",
            "historical_financials": "DART 사업보고서 기준",
            "cash_debt_ratio_order_backlog": "DART 최신 정기보고서 기준",
            "consensus": "CompanyGuide/FnGuide Financial Highlight 표 파싱 기준. 개인 스터디용 참고",
            "community": "디시인사이드 주식갤러리 검색 참고"
        },
        "price": fetch_naver_price(stock_code),
        "weekly_price_summary": weekly_summary(stock_code),
        "historical_financials": historical_financials(corp_code),
        "latest_regular_report": latest_regular_report(corp_code),
        "consensus": fetch_fnguide_consensus(stock_code),
        "recent_news": naver_news(resolved["name"]),
        "dcinside_community": dcinside_links(resolved["name"]),
        "report_prompt_for_gpt": "위 JSON을 바탕으로 1페이지 한국 주식 퀵 스터디 리포트를 작성하세요. 불확실한 항목은 확인 불가로 표시하고, 매수/매도 추천은 하지 마세요."
    }
