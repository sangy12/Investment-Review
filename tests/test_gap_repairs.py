from datetime import UTC, datetime
from unittest.mock import Mock

from tradingagents.dataflows import date_window, router
from tradingagents.dataflows.config import run_config


def test_local_midnight_news_guard_still_rejects_real_future(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 8, 16, 30, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(date_window, "datetime", Clock)
    with run_config({"analysis_timezone": "Asia/Shanghai"}):
        assert date_window.get_current_date() == "2026-11-09"
        dates = [datetime(2026, 11, 1, tzinfo=UTC)]
        assert date_window.coverage_gap(dates, "2026-11-02", "2026-11-09", "Yahoo", "news") is None
        assert "past today" in date_window.coverage_gap(dates, "2026-11-02", "2026-11-10", "Yahoo", "news")
        assert date_window.is_historical("2026-11-08")


def test_china_macro_and_us_cpi_cannot_be_substituted(monkeypatch):
    china, us = Mock(return_value="China"), Mock(return_value="US")
    monkeypatch.setitem(router.VENDOR_METHODS, "get_macro_indicators", {"akshare": china, "fred": us})
    with run_config({"tool_vendors": {"get_macro_indicators": "akshare,fred"}}):
        assert router.route_to_vendor("get_macro_indicators", "cpi", "2026-11-09") == "US"
        china.assert_not_called()
        assert router.route_to_vendor("get_macro_indicators", "china_cpi", "2026-11-09") == "China"


def test_uncovered_yahoo_news_can_reach_configured_domestic_fallback(monkeypatch):
    domestic = Mock(return_value="dated issuer news")
    monkeypatch.setitem(router.VENDOR_METHODS, "get_news", {
        "yfinance": lambda *a: "<Yahoo unavailable for date: recent feed>", "akshare": domestic})
    with run_config({"tool_vendors": {"get_news": "yfinance,akshare"}}):
        assert router.route_to_vendor("get_news", "600519.SS", "2026-11-02", "2026-11-09") == "dated issuer news"
    domestic.assert_called_once()


def test_both_managers_receive_all_original_reports_only_in_opt_in_profile():
    from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
    from tradingagents.agents.managers.research_manager import create_research_manager

    state = {"company_of_interest": "NVDA", "investment_plan": "plan", "trader_investment_plan": "proposal",
             "investment_debate_state": {"history": "debate", "count": 4},
             "risk_debate_state": {"history": "risk", "count": 6, "aggressive_history": "a",
                                   "conservative_history": "c", "neutral_history": "n",
                                   "current_aggressive_response": "a", "current_conservative_response": "c",
                                   "current_neutral_response": "n"}}
    for key in ["market_report", "fundamentals_report", "news_report", "sentiment_report"]:
        state[key] = key + " ORIGINAL fixture"
    for factory in [create_research_manager, create_portfolio_manager]:
        llm = Mock()
        llm.with_structured_output.side_effect = NotImplementedError
        llm.invoke.return_value.content = "**Rating**: Hold"
        with run_config({"direct_analyst_evidence": True}):
            factory(llm)(state)
        prompt = llm.invoke.call_args.args[0]
        assert all(body in prompt for key, body in state.items() if key.endswith('_report'))
        assert "not independently verified" in prompt


def test_quote_timestamp_is_not_misrepresented_as_consensus_timestamp(monkeypatch):
    from tradingagents.dataflows.vendors.yahoo import fundamentals as f

    monkeypatch.setattr(date_window, "get_current_date", lambda: "2026-11-09")
    monkeypatch.setattr(f, "yf_retry", lambda fn: {"longName": "fixture", "currency": "HKD",
                                                  "regularMarketPrice": 420, "regularMarketTime": 1793952000})
    result = f.get_fundamentals("0700.HK", "2026-11-09")
    assert "Regular market price: 420 HKD" in result
    assert "Regular market quote timestamp (UTC): 2026-" in result
    assert "consensus methodology: UNKNOWN" in result


def test_unmatched_summary_gets_literal_pdf_passages_without_false_verification(tmp_path, monkeypatch):
    import hashlib
    import json

    from tradingagents.watchlist import evidence as ev

    url = "https://pdf.dfcfw.com/report.pdf"
    folder = tmp_path / "research_sources/documents"
    folder.mkdir(parents=True)
    name = hashlib.sha256(url.encode()).hexdigest()
    (folder / (name + ".pdf")).write_bytes(b"%PDF fixture")
    (folder / (name + ".json")).write_text(json.dumps({"document_status": "cached_pdf"}))
    source = "Issuer annual report\n单位：人民币元\n" + "x" * 500 + "营业收入：100\n"
    (folder / (name + ".txt")).write_text(source)
    monkeypatch.setattr(ev.requests, "get", Mock(side_effect=AssertionError("No new request")))
    packet = {"as_of": "2026-11-09", "items": [{"kind": "notice", "url": url, "text": "unmatched vendor summary"}]}
    packet["items"].append({"kind": "notice", "url": url, "text": "营业收入：100"})
    ev._attach_documents(packet, {"data_cache_dir": str(tmp_path)}, cached_only=True)
    item = packet["items"][0]
    assert not item["excerpt_in_pdf"]
    assert packet["items"][1]["excerpt_in_pdf"]
    assert packet["items"][1]["primary_pdf_passages"]
    for passage in item["primary_pdf_passages"]:
        start = passage["character_offset"]
        assert source[start:start + len(passage["text"])] == passage["text"]
    assert "require reconciliation" in item["primary_pdf_scope"]
