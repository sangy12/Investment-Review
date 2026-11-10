import json
from unittest.mock import Mock

import pytest

from tradingagents.watchlist import evidence as ev
from tradingagents.watchlist.config import load_config, market_config

HK = {"ticker": "0700.HK", "name": "腾讯控股", "market": "HK"}
PERIOD = "2026-06-30"


def response(tables):
    return {"content": [{"type": "text", "text": json.dumps({"data": tables}, ensure_ascii=False)}]}


def operating(period=PERIOD, code="00700.HK"):
    return {"sheetName": f"{code}主营业务构成({period})", "columns": ["类型", "主营构成", "营业收入(元)", "币种"],
            "items": [["产品", "增值服务", "1945亿", "CNY"]]}


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "today", lambda: "2026-11-08")
    monkeypatch.setattr(ev, "_credential", lambda _: "fixture-private-key")
    monkeypatch.setattr(ev, "_periods", lambda *args: [PERIOD])
    return {"data_cache_dir": str(tmp_path), "research_sources": {"enabled": True, "miaoxiang": True}}


def test_only_matching_operating_tables_enter_packet_not_hkd_or_fcff():
    aggregate = {"columns": ["腾讯控股", "2026中报"], "items": [["FCFF", "173.5亿港元"]]}
    tables = [aggregate, operating(), {**operating(), "sheetName": "00700.HK主营业务构成(2026-06-30)_2"},
              operating("2025-12-31"), operating(code="00999.HK")]
    items, _ = ev.parse_result(response(tables), HK, [PERIOD], "operations_hk", "2026-11-08")
    assert len(items) == 1
    assert items[0]["currency"] == "CNY"
    assert "FCFF" not in json.dumps(items)
    assert "港元" not in json.dumps(items, ensure_ascii=False)


def test_notices_reject_future_signed_links_and_unmatched_issuers():
    table = {"columns": ["标题", "摘要", "发布时间", "跳转链接"], "items": [
        ["腾讯控股中报", "收入", "2026-08-25 17:00:00", "https://pdf.dfcfw.com/pdf/report.pdf"],
        ["腾讯控股中报", "未来", "2099-01-01", "https://pdf.dfcfw.com/pdf/future.pdf"],
        ["其他公司中报", "收入", "2026-08-25", "https://pdf.dfcfw.com/pdf/other.pdf"],
        ["腾讯控股中报", "签名链接", "2026-08-25", "https://example.com/report.pdf?token=fixture"],
    ]}
    items, _ = ev.parse_result(response([table]), HK, [PERIOD], "notices", "2026-11-08")
    assert len(items) == 1 and items[0]["title"] == "腾讯控股中报"


def test_same_period_is_paid_once_per_kind_and_historical_runs_never_fetch(config, monkeypatch):
    call = Mock(return_value=response([operating()]))
    monkeypatch.setattr(ev, "_miaoxiang", call)
    first = ev.prepare_evidence(HK, "2026-11-08", config)
    second = ev.prepare_evidence(HK, "2026-11-08", config)
    assert first["mcp_calls"] == 2 and second["mcp_calls"] == 0
    assert call.call_count == 2
    assert ev.render_evidence(first) == ev.render_evidence(second)
    before = call.call_count
    packet = ev.prepare_evidence(HK, "2020-01-01", config)
    assert packet["items"] == [] and "as-filed" in packet["gaps"][0]
    assert call.call_count == before


def test_failed_paid_calls_are_cached_and_preview_never_spends(config, monkeypatch):
    call = Mock(side_effect=RuntimeError("private key must never be logged"))
    monkeypatch.setattr(ev, "_miaoxiang", call)
    assert ev.prepare_evidence(HK, "2026-11-08", config, cached_only=True)["mcp_calls"] == 0
    assert call.call_count == 0
    first = ev.prepare_evidence(HK, "2026-11-08", config)
    second = ev.prepare_evidence(HK, "2026-11-08", config)
    assert first["mcp_calls"] == 2 and second["mcp_calls"] == 0 and call.call_count == 2
    assert "private key" not in json.dumps(second)


def test_missing_key_or_unknown_period_does_not_spend(config, monkeypatch):
    call = Mock(side_effect=AssertionError("Must not query"))
    monkeypatch.setattr(ev, "_miaoxiang", call)
    monkeypatch.setattr(ev, "_credential", lambda _: "")
    assert ev.prepare_evidence(HK, "2026-11-08", config)["mcp_calls"] == 0
    monkeypatch.setattr(ev, "_credential", lambda _: "fixture")
    monkeypatch.setattr(ev, "_periods", lambda *args: [])
    assert ev.prepare_evidence({**HK, "ticker": "0005.HK"}, "2026-11-08", config)["mcp_calls"] == 0
    call.assert_not_called()


def test_period_discovery_timeout_prevents_paid_fetch(config, monkeypatch):
    import subprocess

    monkeypatch.setattr(ev, "_periods", Mock(side_effect=subprocess.TimeoutExpired("fixture", 45)))
    paid = Mock(side_effect=AssertionError("Must not spend after free discovery timeout"))
    monkeypatch.setattr(ev, "_miaoxiang", paid)
    packet = ev.prepare_evidence(HK, "2026-11-08", config)
    assert packet["mcp_calls"] == 0 and any("TimeoutExpired" in gap for gap in packet["gaps"])
    paid.assert_not_called()


def test_profile_enables_tested_china_statements_news_and_macro():
    cfg = load_config("config/redteam.yaml")
    us = market_config(cfg, {"market": "US"})
    hk = market_config(cfg, HK)
    assert us["data_vendors"] == hk["data_vendors"]
    assert "akshare" not in str(us["tool_vendors"])
    assert set(hk["tool_vendors"]) - set(us["tool_vendors"]) == {
        "get_income_statement", "get_cashflow", "get_balance_sheet", "get_news", "get_macro_indicators"}
    assert hk["tool_vendors"]["get_income_statement"] == "akshare,yfinance"


def test_shared_context_reaches_real_graph_without_llm_or_graph_shape_change():
    from tradingagents.graph.propagation import Propagator
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {"shared_research_evidence": "fixture shared evidence"}
    graph.propagator = Propagator()
    graph.resolve_instrument_context = lambda *args: "instrument identity"
    state = graph.create_run_state("0700.HK", "2026-11-08")
    assert state["instrument_context"] == "instrument identity\n\nfixture shared evidence"


def test_cache_only_pdf_preview_does_not_download(config, monkeypatch):
    packet = {"as_of": "2026-11-08", "items": [{"kind": "notice", "url": "https://pdf.dfcfw.com/report.pdf", "text": "收入"}]}
    get = Mock(side_effect=AssertionError("Cache-only must not download"))
    monkeypatch.setattr(ev.requests, "get", get)
    ev._attach_documents(packet, config, cached_only=True)
    assert packet["items"][0]["document_status"] == "not_downloaded"
    get.assert_not_called()
