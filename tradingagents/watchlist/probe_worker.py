"""One bounded public data probe. Never reads broker accounts or submits orders."""

import contextlib
import io
import json
import sys


def check_data(name):
    if name.startswith("yahoo_"):
        import requests

        ticker = {"yahoo_nvda": "NVDA", "yahoo_maotai": "600519.SS", "yahoo_tencent": "0700.HK"}[name]
        response = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                                params={"range": "5d", "interval": "1d"}, timeout=15)
        response.raise_for_status()
        body = response.json()
        result = (body.get("chart", {}).get("result") or [None])[0]
        quote = ((result or {}).get("indicators", {}).get("quote") or [{}])[0]
        rows = sum(v is not None for v in quote.get("close", []))
        return {"name": name, "status": "data_available" if rows else "no_verified_data",
                "data_accepted": bool(rows), "rows": rows,
                "currency": (result or {}).get("meta", {}).get("currency")}
    if name.startswith("akshare_"):
        from tradingagents.dataflows.vendors.akshare import get_income_statement

        ticker = "600519.SS" if name == "akshare_maotai" else "0700.HK"
        text = get_income_statement(ticker)
        accepted = "REPORT_DATE" in text and not text.startswith("DATA_UNAVAILABLE")
        return {"name": name, "status": "data_available" if accepted else "no_verified_data",
                "data_accepted": accepted, "response_chars": len(text),
                "note": "Current statement retrieval only; does not prove as-filed history."}
    if name == "futu_tencent_news":
        import requests

        response = requests.get("https://ai-news-search.futunn.com/news_search", timeout=15,
                                params={"keyword": "Tencent", "size": 3, "news_type": 1,
                                        "lang": "zh-CN", "sort_type": 2},
                                headers={"User-Agent": "futunn-news-search/0.0.2 (Skill)"})
        response.raise_for_status()
        body = response.json()
        rows = body.get("data") if body.get("code") == 0 else []
        valid = [r for r in rows or [] if isinstance(r, dict) and r.get("title")
                 and r.get("publish_time") and r.get("url")]
        return {"name": name, "status": "data_available" if valid else "no_verified_data",
                "data_accepted": bool(valid), "verified_rows": len(valid),
                "note": "Public retrieval only; no guaranteed free quota or historical coverage."}
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
