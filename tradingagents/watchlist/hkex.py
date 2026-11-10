"""Bounded discovery of issuer filings on HKEXnews's public website. No account API."""

import json
import re
from datetime import datetime, timedelta
from html.parser import HTMLParser

import requests

from tradingagents.dataflows.files import locked
from tradingagents.watchlist.config import today

BASE = "https://www1.hkexnews.hk"


class _Titles(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.cells = None
        self.cell = None
        self.anchor = None
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.cells, self.links = [], []
        elif tag == "td" and self.cells is not None:
            self.cell = []
        elif tag == "a" and self.cell is not None:
            self.anchor = [attrs.get("href", ""), []]

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
        if self.anchor is not None:
            self.anchor[1].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            self.links.append((self.anchor[0], " ".join(" ".join(self.anchor[1]).split())))
            self.anchor = None
        elif tag == "td" and self.cell is not None:
            self.cells.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.cells is not None:
            if len(self.cells) >= 4:
                self.rows.append((self.cells, self.links))
            self.cells, self.cell, self.anchor = None, None, None


def parse_titles(html, code, as_of):
    parser = _Titles()
    parser.feed(html)
    records = []
    for cells, links in parser.rows:
        match = re.search(r"\b(\d{2}/\d{2}/\d{4} \d{2}:\d{2})\b", cells[0])
        codes = re.findall(r"\b\d{5}\b", cells[1])
        if not match or codes != [code]:
            continue
        stamp = datetime.strptime(match[1], "%d/%m/%Y %H:%M")
        if stamp.date().isoformat() > as_of:
            continue
        for path, title in links:
            if not re.fullmatch(r"/listedco/listconews/sehk/\d{4}/\d{4}/[\w-]+\.pdf", path):
                continue
            full_report = bool(re.search(r"\b(?:Interim|Annual|Quarterly) Report\b", title, re.I))
            results = bool(re.search(r"\b(?:INTERIM|ANNUAL|QUARTERLY) RESULTS\b", title, re.I))
            records.append({"kind": "notice", "source": "HKEX issuer filing", "title": title,
                            "issuer_code": code, "issuer_name": cells[2].split(": ")[-1],
                            "published_at": stamp.isoformat() + "+08:00", "url": BASE + path,
                            "category": cells[3].split("Document: ")[-1].split(title)[0].strip(),
                            "financial_report": full_report, "results_announcement": results,
                            "text": title, "period": "UNKNOWN", "currency": "UNKNOWN",
                            "unit": "see original PDF", "verification": "Exact stock-code match on HKEX index; financial fields require PDF reconciliation."})
    return sorted(records, key=lambda row: row["published_at"], reverse=True)


def _discover(ticker, as_of):
    match = re.fullmatch(r"(\d{4,5})\.HK", ticker.upper())
    if not match:
        raise ValueError("not_hk_stock")
    code = match[1].zfill(5)
    with requests.Session() as session:
        response = session.get(BASE + "/search/prefix.do", timeout=15, allow_redirects=False,
                               params={"callback": "callback", "lang": "EN", "type": "A", "name": code, "market": "SEHK"})
        response.raise_for_status()
        # Strict JSONP parsing, never eval external JavaScript.
        matched = re.fullmatch(r"\s*callback\((.*)\);?\s*", response.text, re.S)
        if not matched:
            raise ValueError("invalid_hkex_lookup")
        identities = [row for row in json.loads(matched[1]).get("stockInfo", []) if str(row.get("code")) == code]
        if len(identities) != 1 or not str(identities[0].get("stockId", "")).isdigit():
            raise ValueError("ambiguous_hkex_identity")
        start = datetime.fromisoformat(as_of) - timedelta(days=550)
        response = session.get(BASE + "/search/titlesearch.xhtml", timeout=20, allow_redirects=False,
                               params={"category": "0", "market": "SEHK", "lang": "EN",
                                       "stockId": identities[0]["stockId"], "from": start.strftime("%Y%m%d"),
                                       "to": as_of.replace("-", "")})
        response.raise_for_status()
        if len(response.content) > 3 * 1024 * 1024:
            raise ValueError("hkex_index_size_limit")
        records = parse_titles(response.text, code, as_of)
        if not records:
            raise ValueError("hkex_index_empty_or_changed")
    # Full reports precede other evidence so the display cap retains financial
    # statements rather than a long list of monthly share-return headlines.
    full = next((row for row in records if row["financial_report"]), None)
    result = next((row for row in records if row["results_announcement"]), None)
    selected = [row for row in (full, result) if row]
    selected.extend(row for row in records if row not in selected and
                    "Monthly Return" not in row["title"] and
                    row["published_at"][:10] >= (datetime.fromisoformat(as_of) - timedelta(days=90)).date().isoformat())
    gaps = ["HKEX index: latest visible page within 550 days; bounded selection, not an exhaustive filing archive."]
    if not full:
        gaps.append("HKEX: no full periodic report in visible page; latest official financial period remains UNKNOWN.")
    return selected[:6], gaps


def prepare_hkex_evidence(position, as_of, cfg, *, cached_only=False):
    from tradingagents.watchlist.evidence import _write, cache_path

    if position["market"] != "HK" or as_of != today():
        return [], ["HKEX current discovery withheld for non-HK or historical run."]
    path = cache_path(cfg, position["ticker"], [as_of], "hkex_official_v1")
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked(path):
        if path.exists():
            record = json.loads(path.read_text())
            return record["items"], record["gaps"]
        if cached_only:
            return [], ["HKEX official index cache missing; cache-only preview made no request."]
        try:
            items, gaps = _discover(position["ticker"], as_of)
        except Exception as exc:
            items, gaps = [], [f"HKEX official discovery unavailable ({type(exc).__name__}); not evidence of no filings."]
        _write(path, {"items": items, "gaps": gaps})
    return items, gaps


def financial_passages(text):
    """Literal statement pages including cash-flow continuation, bounded to 14k."""
    selected, remaining = [], 14000
    for number, page in enumerate(text.split("\f"), 1):
        compact = re.sub(r"\s+", " ", page)
        heading = compact[:350].lower()
        is_statement = (any(term in heading for term in (
            "statement of cash flows", "statement of financial position", "statement of profit or loss"))
            or "CASH FLOWS FROM INVESTING ACTIVITIES" in page
            or "total equity" in compact.lower() and "non-current liabilities" in heading)
        if not is_statement or not re.search(r"\d[,.]\d{3}", page):
            continue
        excerpt = page[:min(4000, remaining)]
        selected.append({"pdf_page": number, "text": excerpt, "page_truncated": len(excerpt) < len(page)})
        remaining -= len(excerpt)
        if remaining < 500 or len(selected) >= 6:
            break
    return selected


def financial_period(passages):
    for row in passages:
        match = re.search(r"For the (?:(?:six|three|nine|twelve) months|year) ended ([A-Z][a-z]+ \d{1,2}, \d{4})", row["text"])
        if match:
            return datetime.strptime(match[1], "%B %d, %Y").date().isoformat()
    return "UNKNOWN"
