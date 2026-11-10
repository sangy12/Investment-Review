import json

from tradingagents.watchlist import hkex
from tradingagents.watchlist.evidence import render_evidence


def row(code, stamp, title, path="2026093002173"):
    return f'<tr><td>Release Time: {stamp}</td><td>Stock Code: {code}</td><td>Stock Short Name: MINIMAX-W</td><td>Document: <a href="/listedco/listconews/sehk/2026/0930/{path}.pdf">{title}</a></td></tr>'


def test_index_exact_issuer_cutoff_and_report_classification():
    html = (row("00100", "30/09/2026 19:39", "2026 Interim Report")
            + row("01000", "30/09/2026 19:39", "Wrong issuer")
            + row("00100", "30/12/2099 19:39", "Future")
            + row("00100", "23/10/2026 22:33", "VOLUNTARY ANNOUNCEMENT BUSINESS UPDATE", "2026102301675"))
    items = hkex.parse_titles(html, "00100", "2026-11-10")
    assert len(items) == 2 and items[0]["financial_report"] is False
    assert items[1]["financial_report"] is True and items[1]["period"] == "UNKNOWN"
    assert items[1]["published_at"] == "2026-09-30T19:39:00+08:00"


def test_cashflow_continuation_and_literal_period_are_retained():
    text = ("Cover\fInterim Condensed Consolidated Statement of Profit or Loss\nFor the six months ended June 30, 2026\nUSD'000 Revenue 116,573"
            "\fInterim Condensed Consolidated Statement of Cash Flows\nFor the six months ended June 30, 2026\nUSD'000 Net operating cash (318,106)"
            "\fCASH FLOWS FROM INVESTING ACTIVITIES\nFixed assets (187,626)\nFINANCING ACTIVITIES 791,604")
    passages = hkex.financial_passages(text)
    assert [r["pdf_page"] for r in passages] == [2, 3, 4]
    assert hkex.financial_period(passages) == "2026-06-30"
    assert "318,106" in passages[1]["text"] and "187,626" in passages[2]["text"]


def test_cache_only_and_failures_do_not_trigger_repeated_fetches(tmp_path, monkeypatch):
    monkeypatch.setattr(hkex, "today", lambda: "2026-11-10")
    calls = []

    def fail(*args):
        calls.append(args)
        raise RuntimeError("not for saved output")

    monkeypatch.setattr(hkex, "_discover", fail)
    position = {"ticker": "0100.HK", "market": "HK"}
    cfg = {"data_cache_dir": str(tmp_path)}
    hkex.prepare_hkex_evidence(position, "2026-11-10", cfg, cached_only=True)
    assert not calls
    first = hkex.prepare_hkex_evidence(position, "2026-11-10", cfg)
    second = hkex.prepare_hkex_evidence(position, "2026-11-10", cfg)
    assert first == second and len(calls) == 1
    assert "not for saved output" not in json.dumps(first)
    hkex.prepare_hkex_evidence(position, "2020-01-01", cfg)
    assert len(calls) == 1


def test_financial_document_precedes_headlines_in_display_budget():
    packet = {"items": [{"source": "HKEX issuer filing", "primary_pdf_passages": [{"text": "318,106" * 1500}]}]
              + [{"headline": "price" * 1500} for _ in range(5)], "gaps": []}
    out = render_evidence(packet)
    assert "318,106" in out and "display_omitted_items" in out
