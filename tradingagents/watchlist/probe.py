"""Repeatable, bounded read-only checks. Connectivity is not data acceptance."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import requests

from tradingagents.watchlist.runner import atomic_text

TARGETS = (
    ("openai_auth", "https://auth.openai.com/.well-known/jwks.json"),
    ("openai_models", "https://api.openai.com/v1/models"),
    ("yahoo_nvda", "https://query1.finance.yahoo.com/v8/finance/chart/NVDA?range=5d&interval=1d"),
    ("yahoo_maotai", "https://query1.finance.yahoo.com/v8/finance/chart/600519.SS?range=5d&interval=1d"),
    ("yahoo_tencent", "https://query1.finance.yahoo.com/v8/finance/chart/0700.HK?range=5d&interval=1d"),
    ("akshare_a_origin", "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index"),
    ("akshare_hk_origin", "https://datacenter.eastmoney.com/securities/api/data/v1/get"),
    ("futu_news", "https://ai-news-search.futunn.com/news_search?keyword=Tencent&size=3&news_type=1&lang=zh-CN&sort_type=2"),
    ("ifind_portal", "https://mcp.51ifind.com/"),
    ("miaoxiang_mcp", "https://mxapi.eastmoney.com/mxds/mcp"),
)


def check_network(target):
    name, url = target
    row = {"name": name, "url": url, "data_accepted": False}
    try:
        response = requests.get(url, timeout=10, allow_redirects=False)
        row["http_status"] = response.status_code
        if response.status_code == 401:
            row["status"] = "authentication_required"
        elif response.status_code == 403:
            row["status"] = "forbidden"  # not enough evidence to call this bot detection
        elif response.status_code < 400:
            row["status"] = "reachable"
        else:
            row["status"] = "reachable_http_error"
    except requests.exceptions.ProxyError as exc:
        row["status"] = "network_blocked" if "403" in str(exc) else "proxy_unreachable"
        row["error_type"] = type(exc).__name__
    except requests.RequestException as exc:
        row["status"] = "network_error"
        row["error_type"] = type(exc).__name__
    return row


def _data_job(name):
    """A separate process bounds upstream libraries' own retries and timeouts."""
    try:
        result = subprocess.run([sys.executable, "-m", "tradingagents.watchlist.probe_worker", name],
                                capture_output=True, text=True, timeout=45, check=False)
        # The child redirects SDK prints and emits just one metadata object.
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {"name": name, "status": "timeout", "data_accepted": False}
    except (ValueError, OSError) as exc:
        return {"name": name, "status": "probe_error", "error_type": type(exc).__name__, "data_accepted": False}


def run_probes(output):
    with ThreadPoolExecutor(max_workers=6) as pool:
        network = list(pool.map(check_network, TARGETS))
    by_name = {r["name"]: r for r in network}
    jobs = {
        "yahoo_nvda": "yahoo_nvda", "yahoo_maotai": "yahoo_maotai", "yahoo_tencent": "yahoo_tencent",
        "akshare_maotai": "akshare_a_origin", "akshare_tencent": "akshare_hk_origin",
        "futu_tencent_news": "futu_news",
    }
    data, enabled = [], []
    for job, origin in jobs.items():
        if by_name[origin]["status"] in ("reachable", "reachable_http_error"):
            enabled.append(job)
        else:
            data.append({"name": job, "status": "not_tested_origin_unreachable", "data_accepted": False})
    if enabled:
        with ThreadPoolExecutor(max_workers=3) as pool:
            data.extend(pool.map(_data_job, enabled))
    from tradingagents.dataflows.vendors.akshare import get_income_statement
    from tradingagents.llm_clients import chatgpt_auth

    for ticker in ("600519.SS", "0700.HK"):
        withheld = get_income_statement(ticker, as_of_date="2020-01-01")
        data.append({"name": f"historical_guard_{ticker}",
                     "status": "safety_guard_passed" if withheld.startswith("DATA_UNAVAILABLE") else "guard_failed",
                     "data_accepted": False, "note": "Guard check only; not a live financial-data pass."})
    report = {"generated_at": datetime.now(UTC).isoformat(), "network": network, "data": data,
              "public_data_passed": all(r["data_accepted"] for r in data if r["name"] in jobs),
              "auth": {"credentials_present": bool(chatgpt_auth._read().get("tokens")),
                       "sec_user_agent_configured": bool(os.environ.get("SEC_EDGAR_USER_AGENT"))},
              "pending": ["iFinD/Miaoxiang authenticated tools/list and per-field tests",
                          "Futu quote OAuth scopes and available data rights",
                          "No pricing/free-quota claim has been verified by these probes."]}
    output = Path(output)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    atomic_text(output / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".json"), text)
    atomic_text(output / "latest.json", text)
    return report
