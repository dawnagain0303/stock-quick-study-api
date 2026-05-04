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

app = FastAPI(title="Korean Stock Quick Study API", version="2.3.0")
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
        "version": "v2.3-sales-breakdown"
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


def dart_list_latest_regular_report(corp_code: str) -> Dict[str, Any]:
    """
    DART 공시목록에서 최신 정기보고서(사업/반기/분기)를 찾는다.
    """
    if not DART_API_KEY or not corp_code:
        return {"status": "확인 불가", "note": "DART_API_KEY 또는 corp_code 없음"}

    try:
        today = dt.date.today()
        bgn_de = (today - dt.timedelta(days=900)).strftime("%Y%m%d")
        end_de = today.strftime("%Y%m%d")
        url = "https://opendart.fss.or.kr/api/list.json"
        params = {
            "crtfc_key": DART_API_KEY,
            "corp_code": corp_code,
            "bgn_de": bgn_de,
            "end_de": end_de,
            "page_no": 1,
            "page_count": 100
        }
        js = requests.get(url, params=params, timeout=15).json()
        if js.get("status") != "000":
            return {"status": "확인 불가", "note": js.get("message", "DART list 조회 실패")}

        items = []
        for it in js.get("list", []):
            rn = it.get("report_nm", "")
            if any(k in rn for k in ["사업보고서", "반기보고서", "분기보고서"]):
                # 정정 보고서도 최신이면 허용하되 첨부정정 등 이상한 것은 제외
                items.append({
                    "rcept_no": it.get("rcept_no"),
                    "report_nm": rn,
                    "rcept_dt": it.get("rcept_dt"),
                    "corp_name": it.get("corp_name")
                })

        if not items:
            return {"status": "확인 불가", "note": "최근 900일 내 정기보고서 없음"}

        items.sort(key=lambda x: x.get("rcept_dt", ""), reverse=True)
        latest = items[0]
        latest["status"] = "ok"
        return latest

    except Exception as e:
        return {"status": "확인 불가", "note": "DART 공시목록 조회 중 오류", "error": str(e)}


def dart_download_document_xml(rcept_no: str) -> Dict[str, Any]:
    """
    DART document.xml로 보고서 원문 zip을 받아 텍스트/테이블 탐색용 soup 목록을 만든다.
    """
    if not DART_API_KEY or not rcept_no:
        return {"status": "확인 불가", "note": "DART_API_KEY 또는 rcept_no 없음", "docs": []}

    try:
        url = "https://opendart.fss.or.kr/api/document.xml"
        r = requests.get(url, params={"crtfc_key": DART_API_KEY, "rcept_no": rcept_no}, timeout=25)

        # 에러는 XML 텍스트로 오는 경우가 있음
        if not r.content.startswith(b"PK\x03\x04"):
            try:
                msg = r.content.decode("utf-8", errors="replace")[:500]
            except Exception:
                msg = str(r.content[:200])
            return {"status": "확인 불가", "note": "DART document 다운로드 실패", "raw": msg, "docs": []}

        z = zipfile.ZipFile(io.BytesIO(r.content))
        docs = []
        for name in z.namelist():
            if not name.lower().endswith((".xml", ".html", ".htm")):
                continue
            raw = z.read(name)
            html = None
            for enc in ["utf-8", "cp949", "euc-kr"]:
                try:
                    html = raw.decode(enc)
                    break
                except Exception:
                    continue
            if html is None:
                html = raw.decode("utf-8", errors="replace")

            soup = BeautifulSoup(html, "html.parser")
            docs.append({
                "filename": name,
                "html_len": len(html),
                "soup": soup
            })

        return {"status": "ok", "docs": docs, "file_count": len(docs)}

    except Exception as e:
        return {"status": "확인 불가", "note": "DART document 원문 처리 중 오류", "error": str(e), "docs": []}


def normalize_backlog_text(s: Any) -> str:
    return re.sub(r"\s+", "", str(s or "").replace("\xa0", " "))


def table_to_matrix(table) -> List[List[str]]:
    matrix = []
    for tr in table.select("tr"):
        row = []
        for cell in tr.select("th,td"):
            txt = cell.get_text(" ", strip=True)
            if txt:
                row.append(txt)
            else:
                row.append("")
        if any(x.strip() for x in row):
            matrix.append(row)
    return matrix


def parse_money_like(value: str):
    if value is None:
        return None
    s = str(value).strip()
    if s in ["", "-", "N/A", "해당사항 없음", "해당사항없음"]:
        return None
    # 괄호 음수, 쉼표, 소수 대응
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    cleaned = re.sub(r"[^0-9.\-]", "", s)
    if cleaned in ["", "-", "."]:
        return None
    try:
        v = float(cleaned)
        if neg:
            v = -v
        return int(v) if v.is_integer() else v
    except Exception:
        return None


def detect_unit_near_text(text: str) -> Optional[str]:
    candidates = [
        "단위: 백만원", "단위 : 백만원", "단위:백만원",
        "단위: 천원", "단위 : 천원", "단위:천원",
        "단위: 원", "단위 : 원", "단위:원",
        "단위: 억원", "단위 : 억원", "단위:억원",
        "백만원", "천원", "억원"
    ]
    for c in candidates:
        if c in text:
            if "백만원" in c:
                return "백만원"
            if "천원" in c:
                return "천원"
            if "억원" in c:
                return "억원"
            if "원" in c:
                return "원"
    return None


def score_order_backlog_table(matrix: List[List[str]], context_text: str) -> int:
    text = normalize_backlog_text(" ".join([" ".join(r) for r in matrix]) + " " + context_text)
    score = 0
    keywords = {
        "수주상황": 60,
        "수주잔고": 90,
        "수주총액": 50,
        "기초수주잔고": 50,
        "기말수주잔고": 80,
        "계약잔액": 80,
        "잔여계약": 80,
        "미이행수행의무": 90,
        "이행되지않은수행의무": 90,
        "수주액": 30,
        "납품액": 30,
        "매출액": 10
    }
    for k, pts in keywords.items():
        if k in text:
            score += pts
    # 숫자가 많을수록 표일 가능성 증가
    num_count = sum(1 for row in matrix for cell in row if parse_money_like(cell) is not None)
    score += min(num_count, 30)
    # 너무 작은 표는 감점
    if len(matrix) < 2:
        score -= 50
    return score


def extract_context_around_table(table, chars: int = 500) -> str:
    parts = []
    # 이전 형제 몇 개
    prevs = []
    p = table
    for _ in range(8):
        p = p.find_previous()
        if not p:
            break
        if p.name in ["p", "div", "span", "title", "section", "h1", "h2", "h3", "h4"]:
            txt = p.get_text(" ", strip=True)
            if txt:
                prevs.append(txt)
    parts.extend(reversed(prevs[-5:]))
    parts.append(table.get_text(" ", strip=True)[:chars])
    return " ".join(parts)[-chars:]


def matrix_to_backlog_summary(matrix: List[List[str]], unit: Optional[str]) -> Dict[str, Any]:
    """
    다양한 수주잔고 표를 일반화해서 반환.
    v2.2 개선: '당기말 수주잔(YYYY.MM.DD)' 같은 컬럼을 period가 아니라 backlog로 정확히 잡는다.
    """
    if not matrix:
        return {"status": "확인 불가", "note": "빈 표"}

    # 첫 행 또는 앞 2행을 헤더 후보로 사용
    header = matrix[0]
    if len(matrix) > 1 and len(matrix[1]) > len(header):
        # 첫 행이 단일 제목행이면 두 번째 행을 헤더로
        if len(header) <= 2:
            header = matrix[1]

    norm_headers = [normalize_backlog_text(h) for h in header]

    col_map = {}
    for idx, h in enumerate(norm_headers):
        # 1순위: 수주잔고/계약잔액/미이행/잔여 관련 컬럼은 무조건 backlog
        if any(k in h for k in [
            "당기말수주잔", "기말수주잔", "전기말수주잔", "수주잔고", "수주잔",
            "계약잔액", "잔여계약", "잔여수주", "미이행", "수행의무잔액"
        ]):
            # 당기말/기말/잔여/미이행/계약잔액을 우선
            if "backlog" not in col_map or any(k in h for k in ["당기말", "기말", "잔여", "미이행", "계약잔액"]):
                col_map["backlog"] = idx
            continue

        # 2순위: 수주액/계약금액
        if any(k in h for k in ["당기수주액", "수주총액", "수주액", "계약금액", "총계약"]):
            col_map.setdefault("order_amount", idx)
            continue

        # 3순위: 매출/납품/기납품
        if any(k in h for k in ["당기매출액", "기납품", "납품액", "매출액", "수익인식", "이행금액"]):
            col_map.setdefault("delivered_amount", idx)
            continue

        # 4순위: 분류 컬럼
        if any(k in h for k in ["사업부문", "품목", "부문", "사업", "공사", "프로젝트", "구분", "회사", "지배회사"]):
            col_map.setdefault("category", idx)
            continue

        # 5순위: 순수 기간 컬럼만 period. 단, 수주/잔고/잔액 들어가면 period로 보지 않음.
        if any(k in h for k in ["기간", "연도"]) and not any(k in h for k in ["수주", "잔고", "잔액"]):
            col_map.setdefault("period", idx)
            continue

    items = []
    start_row = 1
    if len(matrix) > 1 and header == matrix[1]:
        start_row = 2

    for row in matrix[start_row:]:
        if not row or len(row) < 2:
            continue

        item = {}
        for key, idx in col_map.items():
            if idx < len(row):
                val = row[idx]
                if key in ["order_amount", "delivered_amount", "backlog"]:
                    item[key] = parse_money_like(val)
                    item[key + "_raw"] = val
                else:
                    item[key] = val

        # 보기 좋게 사업부문/회사/품목 앞쪽 텍스트 컬럼을 묶은 설명 추가
        text_cols = []
        for c in row[:3]:
            if parse_money_like(c) is None and str(c).strip():
                text_cols.append(str(c).strip())
        if text_cols:
            item.setdefault("description", " / ".join(text_cols))

        # 컬럼 매핑 실패 시 행 전체 유지
        if not item:
            nums = [parse_money_like(x) for x in row]
            if any(x is not None for x in nums):
                item = {"raw_row": row, "numbers": nums}

        if item:
            items.append(item)

    # 핵심 backlog 총액 후보: backlog 컬럼 중 마지막/합계/계 행 우선, 아니면 첫 유효값
    backlog_candidates = []
    for it in items:
        if it.get("backlog") is not None:
            label = normalize_backlog_text(str(it.get("category", "")) + str(it.get("period", "")) + str(it.get("description", "")) + str(it))
            priority = 0
            if "합계" in label or "총계" in label:
                priority += 20
            if "중공업" in label:
                priority += 5
            backlog_candidates.append((priority, it.get("backlog"), it))
    backlog_candidates.sort(key=lambda x: x[0], reverse=True)

    return {
        "unit": unit,
        "columns_detected": col_map,
        "items": items[:30],
        "backlog_best_candidate": backlog_candidates[0][1] if backlog_candidates else None,
        "backlog_best_row": backlog_candidates[0][2] if backlog_candidates else None,
        "raw_table_preview": matrix[:12]
    }

def fetch_order_backlog(corp_code: str) -> Dict[str, Any]:
    """
    최신 정기보고서 원문에서 수주잔고/수주상황/계약잔액/미이행 수행의무 표를 탐색.
    """
    latest = dart_list_latest_regular_report(corp_code)
    if latest.get("status") != "ok":
        return {
            "status": "확인 불가",
            "note": "최신 정기보고서 조회 실패",
            "latest_report": latest
        }

    doc = dart_download_document_xml(latest.get("rcept_no"))
    if doc.get("status") != "ok":
        return {
            "status": "확인 불가",
            "note": "최신 정기보고서 원문 다운로드 실패",
            "latest_report": latest,
            "document_status": {k: v for k, v in doc.items() if k != "docs"}
        }

    keywords = [
        "수주잔고", "수주상황", "수주총액", "기말수주잔고", "계약잔액",
        "잔여계약", "미이행 수행의무", "미이행수행의무", "이행되지 않은 수행의무"
    ]

    candidates = []
    full_text_hits = []

    for d in doc.get("docs", []):
        soup = d["soup"]
        text = soup.get_text(" ", strip=True)
        norm_text = normalize_backlog_text(text)
        for kw in keywords:
            if normalize_backlog_text(kw) in norm_text:
                full_text_hits.append({"filename": d["filename"], "keyword": kw})

        for ti, table in enumerate(soup.select("table")):
            matrix = table_to_matrix(table)
            if not matrix:
                continue
            context = extract_context_around_table(table)
            score = score_order_backlog_table(matrix, context)
            if score <= 30:
                continue
            unit = detect_unit_near_text(context + " " + table.get_text(" ", strip=True))
            summary = matrix_to_backlog_summary(matrix, unit)
            candidates.append({
                "filename": d["filename"],
                "table_index": ti,
                "score": score,
                "context_preview": context[-500:],
                "summary": summary
            })

    if not candidates:
        return {
            "status": "확인 불가",
            "note": "정기보고서 원문에서 수주잔고 관련 표를 찾지 못함. 수주산업이 아니거나 표기가 다른 경우일 수 있음.",
            "latest_report": latest,
            "keyword_hits": full_text_hits[:20]
        }

    candidates.sort(key=lambda x: x["score"], reverse=True)
    best = candidates[0]

    return {
        "status": "ok",
        "source": "DART document.xml",
        "latest_report": latest,
        "matched_table": {
            "filename": best["filename"],
            "table_index": best["table_index"],
            "score": best["score"],
            "context_preview": best["context_preview"]
        },
        "unit": best["summary"].get("unit"),
        "backlog_best_candidate": best["summary"].get("backlog_best_candidate"),
        "backlog_best_row": best["summary"].get("backlog_best_row"),
        "items": best["summary"].get("items"),
        "columns_detected": best["summary"].get("columns_detected"),
        "raw_table_preview": best["summary"].get("raw_table_preview"),
        "other_candidate_count": len(candidates) - 1,
        "note": "DART 최신 정기보고서 본문 표 자동 파싱 결과. 회사별 표 구조가 달라 검증 필요."
    }


def score_sales_breakdown_table(matrix: List[List[str]], context_text: str) -> int:
    text = normalize_backlog_text(" ".join([" ".join(r) for r in matrix]) + " " + context_text)
    score = 0
    for k, pts in {
        "매출현황": 70, "매출실적": 80, "매출액": 40, "매출비중": 90,
        "비중": 35, "사업부문": 50, "제품": 30, "품목": 30,
        "주요제품": 50, "주요제품등": 60, "제품및서비스": 50,
        "영업수익": 35, "사업의내용": 15
    }.items():
        if k in text:
            score += pts

    if any(k in text for k in ["수주잔고", "수주상황", "수주총액", "기말수주잔고", "계약잔액"]):
        score -= 150

    num_count = sum(1 for row in matrix for cell in row if parse_money_like(cell) is not None)
    score += min(num_count, 30)
    if len(matrix) < 2:
        score -= 50
    return score


def matrix_to_sales_breakdown(matrix: List[List[str]], unit: Optional[str]) -> Dict[str, Any]:
    if not matrix:
        return {"status": "확인 불가", "note": "빈 표"}

    header = matrix[0]
    if len(matrix) > 1 and len(matrix[1]) > len(header) and len(header) <= 2:
        header = matrix[1]

    norm_headers = [normalize_backlog_text(h) for h in header]
    col_map = {}

    for idx, h in enumerate(norm_headers):
        if any(k in h for k in ["사업부문", "부문", "제품", "품목", "구분", "사업", "서비스", "매출유형", "제품명"]):
            col_map.setdefault("category", idx)
            continue
        if any(k in h for k in ["매출액", "매출실적", "영업수익", "수익"]):
            if any(k in h for k in ["당기", "2025", "최근"]):
                col_map["revenue"] = idx
            else:
                col_map.setdefault("revenue", idx)
            continue
        if any(k in h for k in ["비중", "구성비", "점유율"]):
            col_map.setdefault("share", idx)
            continue
        if any(k in h for k in ["기간", "연도", "당기", "전기"]):
            col_map.setdefault("period", idx)
            continue

    items = []
    start_row = 1
    if len(matrix) > 1 and header == matrix[1]:
        start_row = 2

    for row in matrix[start_row:]:
        if not row or len(row) < 2:
            continue

        item = {}
        for key, idx in col_map.items():
            if idx < len(row):
                val = row[idx]
                if key == "revenue":
                    item["revenue"] = parse_money_like(val)
                    item["revenue_raw"] = val
                elif key == "share":
                    item["share"] = parse_money_like(val)
                    item["share_raw"] = val
                else:
                    item[key] = val

        text_cols = []
        for c in row[:3]:
            if parse_money_like(c) is None and str(c).strip():
                text_cols.append(str(c).strip())
        if text_cols:
            item.setdefault("description", " / ".join(text_cols))

        if item.get("revenue") is None:
            nums = [parse_money_like(x) for x in row]
            nums_clean = [x for x in nums if isinstance(x, (int, float))]
            if nums_clean:
                item.setdefault("revenue", max(nums_clean))
                for c in row:
                    if parse_money_like(c) == item["revenue"]:
                        item.setdefault("revenue_raw", c)
                        break

        if "share" not in item:
            for c in row:
                if "%" in str(c):
                    item["share"] = parse_money_like(c)
                    item["share_raw"] = c
                    break

        if item and (item.get("revenue") is not None or item.get("share") is not None or item.get("description")):
            items.append(item)

    valid_items = []
    for it in items:
        label = normalize_backlog_text(str(it.get("category", "")) + str(it.get("description", "")))
        if "합계" in label or "총계" in label or label == "계":
            continue
        if isinstance(it.get("revenue"), (int, float)):
            valid_items.append(it)

    total_revenue = sum(it["revenue"] for it in valid_items) if valid_items else None
    if total_revenue:
        for it in valid_items:
            if it.get("share") is None and it.get("revenue") is not None:
                it["share_calculated"] = round(it["revenue"] / total_revenue * 100, 1)

    items_sorted = sorted(items, key=lambda x: x.get("revenue") if isinstance(x.get("revenue"), (int, float)) else -1, reverse=True)

    return {
        "unit": unit,
        "columns_detected": col_map,
        "items": items_sorted[:30],
        "total_revenue_detected": total_revenue,
        "raw_table_preview": matrix[:12]
    }


def fetch_sales_breakdown(corp_code: str) -> Dict[str, Any]:
    latest = dart_list_latest_regular_report(corp_code)
    if latest.get("status") != "ok":
        return {"status": "확인 불가", "note": "최신 정기보고서 조회 실패", "latest_report": latest}

    doc = dart_download_document_xml(latest.get("rcept_no"))
    if doc.get("status") != "ok":
        return {
            "status": "확인 불가",
            "note": "최신 정기보고서 원문 다운로드 실패",
            "latest_report": latest,
            "document_status": {k: v for k, v in doc.items() if k != "docs"}
        }

    candidates = []
    keyword_hits = []
    keywords = ["매출실적", "매출현황", "매출액", "매출비중", "주요제품", "제품및서비스", "사업부문"]

    for d in doc.get("docs", []):
        soup = d["soup"]
        norm_doc = normalize_backlog_text(soup.get_text(" ", strip=True))
        for kw in keywords:
            if normalize_backlog_text(kw) in norm_doc:
                keyword_hits.append({"filename": d["filename"], "keyword": kw})

        for ti, table in enumerate(soup.select("table")):
            matrix = table_to_matrix(table)
            if not matrix:
                continue
            context = extract_context_around_table(table)
            score = score_sales_breakdown_table(matrix, context)
            if score <= 60:
                continue
            unit = detect_unit_near_text(context + " " + table.get_text(" ", strip=True))
            summary = matrix_to_sales_breakdown(matrix, unit)
            if not summary.get("items"):
                continue
            candidates.append({
                "filename": d["filename"],
                "table_index": ti,
                "score": score,
                "context_preview": context[-500:],
                "summary": summary
            })

    if not candidates:
        return {
            "status": "확인 불가",
            "note": "정기보고서 원문에서 사업부문/제품별 매출 구성표를 찾지 못함",
            "latest_report": latest,
            "keyword_hits": keyword_hits[:20]
        }

    candidates.sort(key=lambda x: x["score"], reverse=True)
    best = candidates[0]
    return {
        "status": "ok",
        "source": "DART document.xml",
        "latest_report": latest,
        "matched_table": {
            "filename": best["filename"],
            "table_index": best["table_index"],
            "score": best["score"],
            "context_preview": best["context_preview"]
        },
        "unit": best["summary"].get("unit"),
        "items": best["summary"].get("items"),
        "columns_detected": best["summary"].get("columns_detected"),
        "total_revenue_detected": best["summary"].get("total_revenue_detected"),
        "raw_table_preview": best["summary"].get("raw_table_preview"),
        "other_candidate_count": len(candidates) - 1,
        "note": "DART 최신 정기보고서 본문 표 자동 파싱 결과. 회사별 표 구조가 달라 검증 필요."
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
            "cash_debt_ratio_order_backlog": "DART 최신 정기보고서 기준. 수주잔고는 DART 정기보고서 원문 표 파싱 기준",
            "consensus": "CompanyGuide/FnGuide Financial Highlight 표 파싱 기준. 개인 스터디용 참고",
            "community": "디시인사이드 주식갤러리 검색 참고"
        },
        "price": fetch_naver_price(stock_code),
        "weekly_price_summary": weekly_summary(stock_code),
        "historical_financials": historical_financials(corp_code),
        "latest_regular_report": latest_regular_report(corp_code),
        "order_backlog": fetch_order_backlog(corp_code),
        "sales_breakdown": fetch_sales_breakdown(corp_code),
        "consensus": fetch_fnguide_consensus(stock_code),
        "recent_news": naver_news(resolved["name"]),
        "dcinside_community": dcinside_links(resolved["name"]),
        "report_prompt_for_gpt": "위 JSON을 바탕으로 1페이지 한국 주식 퀵 스터디 리포트를 작성하세요. 불확실한 항목은 확인 불가로 표시하고, 매수/매도 추천은 하지 마세요."
    }
