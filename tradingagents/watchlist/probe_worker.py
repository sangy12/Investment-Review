"""One bounded public data probe. Never reads broker accounts or submits orders."""

import contextlib
import io
import json
import sys
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import pandas as pd


def check_data(name):
    if name.startswith("yahoo_"):
        from tradingagents.dataflows.date_window import get_current_date
        from tradingagents.dataflows.vendors.yahoo.market import get_YFin_data_online

        ticker = {"yahoo_nvda": "NVDA", "yahoo_maotai": "600519.SS", "yahoo_tencent": "0700.HK"}[name]
        end = get_current_date()
        start = (pd.Timestamp(end) - timedelta(days=10)).strftime("%Y-%m-%d")
        # Exercise the report's actual yfinance client. A plain requests probe
        # can return 429 even when this client's supported session succeeds.
        text = get_YFin_data_online(ticker, start, end)
        frame = pd.read_csv(io.StringIO(text), comment="#")
        dates = pd.to_datetime(frame["Date"], errors="coerce")
        closes = pd.to_numeric(frame["Close"], errors="coerce")
        valid = dates.notna() & dates.between(pd.Timestamp(start), pd.Timestamp(end)) & closes.notna()
        rows = int(valid.sum())
        return {"name": name, "status": "data_available" if rows else "no_verified_data",
                "data_accepted": bool(rows), "rows": rows,
                "latest_date": dates[valid].max().strftime("%Y-%m-%d") if rows else None,
                "client": "production yfinance adapter",
                "note": "Price retrieval only; currency and fundamentals require separate verification."}
    if name.startswith("akshare_"):
        from tradingagents.dataflows.vendors import akshare

        ticker = "600519.SS" if "maotai" in name else "0700.HK"
        kind = "balance" if name.endswith("_balance") else "cashflow" if name.endswith("_cashflow") else "income"
        method = {"income": akshare.get_income_statement, "balance": akshare.get_balance_sheet,
                  "cashflow": akshare.get_cashflow}[kind]
        text = method(ticker)
        frame = pd.read_csv(io.StringIO(text), comment="#")
        dates = pd.to_datetime(frame["REPORT_DATE"], errors="coerce")
        # A header or empty table is not evidence of live financial data.
        value_column = "AMOUNT" if ticker.endswith(".HK") else {
            "income": "OPERATE_INCOME", "balance": "TOTAL_ASSETS", "cashflow": "NETCASH_OPERATE",
        }[kind]
        values = pd.to_numeric(frame[value_column], errors="coerce")
        accepted = bool((dates.notna() & values.notna()).any())
        currency = [c for c in frame if "CURRENCY" in c.upper() or "币种" in c]
        units = [c for c in frame if "UNIT" in c.upper() or "单位" in c]
        return {"name": name, "status": "data_available" if accepted else "no_verified_data",
                "data_accepted": accepted, "rows": len(frame), "statement": kind,
                "report_dates": sorted(dates.dropna().dt.strftime("%Y-%m-%d").unique().tolist(), reverse=True),
                "currency_metadata": {c: frame[c].dropna().astype(str).unique().tolist()[:4] for c in currency},
                "unit_metadata": {c: frame[c].dropna().astype(str).unique().tolist()[:4] for c in units},
                "note": "Current retrieval only; absent currency/units are UNKNOWN. Reporting periods are not verified standalone quarters or as-filed history."}
    if name.startswith("futu_tencent_"):
        import requests

        news_type = {"futu_tencent_news": 1, "futu_tencent_notice": 2, "futu_tencent_research": 3}[name]
        response = requests.get("https://ai-news-search.futunn.com/news_search", timeout=15,
                                params={"keyword": "Tencent", "size": 3, "news_type": news_type,
                                        "lang": "zh-CN", "sort_type": 2},
                                headers={"User-Agent": "futunn-news-search/0.0.2 (Skill)"})
        response.raise_for_status()
        body = response.json()
        rows = body.get("data") if body.get("code") == 0 else []
        valid = []
        for row in rows or []:
            if not isinstance(row, dict) or not row.get("title"):
                continue
            try:
                stamp = float(row.get("publish_time", ""))
                stamp = stamp / 1000 if stamp > 1e12 else stamp
                url = urlparse(row.get("url", ""))
                if not (0 < stamp <= datetime.now(UTC).timestamp() and url.scheme == "https" and url.netloc):
                    continue
                valid.append({"title": row["title"], "published_at_utc": datetime.fromtimestamp(stamp, UTC).isoformat(),
                              "url": row["url"]})
            except (ValueError, TypeError, OverflowError, OSError):
                continue
        return {"name": name, "status": "data_available" if valid else "no_verified_data",
                "data_accepted": bool(valid), "verified_rows": len(valid), "items": valid,
                "note": "Public keyword results; issuer identity and original full text unverified. No guaranteed free quota or historical coverage."}
    raise ValueError("Unknown read-only probe")


def main():
    name = sys.argv[1]
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = check_data(name)
    except Exception as exc:
        result = {"name": name, "status": "data_error", "error_type": type(exc).__name__, "data_accepted": False}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
