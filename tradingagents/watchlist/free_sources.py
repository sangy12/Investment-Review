"""Daily cached, read-only forecast and community evidence shared by all agents."""

import html
import json
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import requests

from tradingagents.dataflows.files import locked
from tradingagents.watchlist.config import today
from tradingagents.watchlist.evidence import _write, cache_path


def forecast_items(position):
    result = subprocess.run([sys.executable, "-m", "tradingagents.dataflows.forecast_worker",
                             position["ticker"], position["market"]],
                            capture_output=True, text=True, check=True, timeout=45)
    if len(result.stdout) > 200000:
        raise ValueError("forecast_response_size_limit")
    tables = json.loads(result.stdout)
    items = []
    for table in tables:
        if not isinstance(table, dict) or not table.get("rows"):
            continue
        items.append({"kind": "consensus_snapshot", "ticker": position["ticker"],
                      "source": {"US": "Yahoo Finance", "A_SHARE": "AKShare / THS", "HK": "AKShare / ETNet"}[position["market"]],
                      "retrieved_at": datetime.now(UTC).isoformat(), "title": table["title"],
                      "columns": table["columns"], "rows": table["rows"],
                      "currency": "preserved per cell if supplied; otherwise UNKNOWN",
                      "unit": "vendor table units; UNKNOWN when absent; no conversion",
                      "formation_time": "UNKNOWN", "published_at": None,
                      "verification": "Current vendor forecasts, not actual results or issuer guidance. "
                                      "Fiscal period, analyst coverage, GAAP/adjusted basis and aggregation methodology "
                                      "must be preserved where supplied, otherwise UNKNOWN. Relative quarter/year labels "
                                      "are vendor snapshot labels; do not invent period end dates or historical vintages."})
    return items


def parse_community(body, position, date, *, now=None):
    if body.get("code") != 0 or not isinstance(body.get("data"), list):
        raise ValueError("community_response_unavailable")
    now = now or datetime.now(UTC)
    aliases = {position["name"], position["ticker"], position["ticker"].split(".")[0]}
    aliases.update({"0700.HK": ["腾讯", "00700"], "600519.SS": ["茅台"]}.get(position["ticker"], []))
    end = min(datetime.fromisoformat(date + "T00:00:00+08:00") + timedelta(days=1), now)
    start = datetime.fromisoformat(date + "T00:00:00+08:00") - timedelta(days=6)
    items, seen = [], set()
    for row in body["data"][:50]:
        if not isinstance(row, dict):
            continue
        text = html.unescape(re.sub(r"<[^>]*>", " ", str(row.get("title", "")) + " " + str(row.get("desc", ""))))
        text = re.sub(r"\s+", " ", text).strip()
        try:
            stamp = float(row["publish_time"])
            published = datetime.fromtimestamp(stamp / 1000 if stamp > 1e12 else stamp, UTC)
        except (ValueError, TypeError, KeyError, OverflowError, OSError):
            continue
        if not (start <= published <= end) or len(text) < 20 or not any(a.casefold() in text.casefold() for a in aliases):
            continue
        identity = re.sub(r"\W+", "", text).casefold()
        if identity in seen:
            continue
        seen.add(identity)
        url = urlparse(str(row.get("url", "")))
        link = None
        if url.scheme == "https" and not url.username and not url.password and (url.hostname == "futunn.com" or (url.hostname or "").endswith(".futunn.com")):
            link = url._replace(query="", fragment="").geturl()
        items.append({"kind": "community_post", "source": "Futu public stock_feed",
                      "ticker": position["ticker"], "text": text[:600], "published_at": published.isoformat(),
                      "retrieved_at": now.isoformat(), "url": link,
                      "sentiment": "UNCLASSIFIED", "interactions": "UNKNOWN",
                      "verification": "Keyword-associated public opinion, not issuer disclosure or market-wide sentiment. "
                                      "Limited recent sample; do not invent bull/bear percentages, popularity or historical coverage."})
    return sorted(items, key=lambda item: item["published_at"], reverse=True)[:5]


def community_items(position, date):
    with requests.get("https://ai-news-search.futunn.com/stock_feed", timeout=15, allow_redirects=False,
                      stream=True, params={"keyword": position["name"], "size": 30}) as response:
        if response.status_code != 200:
            raise ValueError("community_http_error")
        content = bytearray()
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content) > 1024 * 1024:
                raise ValueError("community_response_size_limit")
    return parse_community(json.loads(content), position, date)


def prepare_free_evidence(position, date, cfg, *, cached_only=False):
    items, gaps = [], []
    if date != today():
        return [], ["DATA_UNAVAILABLE: forecasts/community have no verified historical vintage."]
    options = cfg.get("research_sources", {})
    jobs = []
    if options.get("consensus_snapshots"):
        jobs.append(("forecasts_v1", lambda: forecast_items(position)))
    if options.get("futu_community") and position["market"] == "HK":
        jobs.append(("community_v1", lambda: community_items(position, date)))
    for kind, fetch in jobs:
        path = cache_path(cfg, position["ticker"], [date], kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with locked(path):
                if path.exists():
                    record = json.loads(path.read_text())
                elif cached_only:
                    gaps.append(f"{kind}: cached snapshot unavailable; no request made.")
                    continue
                else:
                    try:
                        rows = fetch()
                        record = {"items": rows, "gaps": [] if rows else [f"{kind}: no valid samples; not evidence of no forecasts/discussion."]}
                    except Exception as exc:
                        record = {"items": [], "gaps": [f"{kind} unavailable ({type(exc).__name__}); not evidence of absence."]}
                    _write(path, record)  # Cache failures too, avoid repeated retries by every agent.
            items.extend(record["items"])
            gaps.extend(record["gaps"])
        except (ValueError, KeyError, OSError) as exc:
            gaps.append(f"{kind} cache unavailable ({type(exc).__name__}).")
    return items, gaps
