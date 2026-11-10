from unittest.mock import Mock

import pandas as pd
import pytest

from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError
from tradingagents.dataflows.vendors import akshare as vendor


@pytest.mark.parametrize("ticker", ["600519.SS", "000001.SZ", "0700.HK"])
@pytest.mark.parametrize("method", ["get_fundamentals", "get_balance_sheet", "get_cashflow", "get_income_statement"])
def test_historical_fundamentals_unavailable_before_network(monkeypatch, ticker, method):
    call = Mock(side_effect=AssertionError("Historical snapshots must never be requested"))
    monkeypatch.setattr(vendor, "_call", call)
    result = getattr(vendor, method)(ticker, as_of_date="2020-01-01")
    assert "DATA_UNAVAILABLE" in result and "数据不可用" in result
    call.assert_not_called()


@pytest.mark.parametrize("ticker,symbol,method", [
    ("600519.SS", "SH600519", "stock_profit_sheet_by_report_em"),
    ("000001.SZ", "SZ000001", "stock_profit_sheet_by_report_em"),
    ("0700.HK", "00700", "stock_financial_hk_report_em"),
])
def test_statement_symbol_routing_and_no_future_rows(monkeypatch, ticker, symbol, method):
    call = Mock(return_value=pd.DataFrame({"REPORT_DATE": ["2025-12-31", "2099-12-31"], "Revenue": [100, 999]}))
    monkeypatch.setattr(vendor, "_call", call)
    result = vendor.get_income_statement(ticker)
    assert "100" in result and "999" not in result
    assert call.call_args.args[0] == method
    assert symbol in call.call_args.kwargs.values()


def test_price_window_uses_unadjusted_prices_and_trims_future(monkeypatch):
    call = Mock(return_value=pd.DataFrame({"日期": ["2020-01-01", "2020-01-02", "2020-01-03"], "开盘": [1, 2, 3], "最高": [1, 2, 3], "最低": [1, 2, 3], "收盘": [1, 2, 999], "成交量": [1, 2, 3]}))
    monkeypatch.setattr(vendor, "_call", call)
    result = vendor.get_stock_data("600519.SS", "2020-01-01", "2020-01-02")
    assert "999" not in result
    assert call.call_args.kwargs["adjust"] == ""


def test_news_filters_after_cutoff_and_hk_does_not_search_ambiguous_code(monkeypatch):
    monkeypatch.setattr(vendor, "_call", Mock(side_effect=AssertionError))
    with pytest.raises(NoMarketDataError):
        vendor.get_news("0700.HK", "2020-01-01", "2020-01-02")
    frame = pd.DataFrame({"发布时间": ["2020-01-01 12:00", "2020-01-03 12:00"], "标题": ["known", "future"]})
    result = vendor._news_window(frame, "2020-01-01", "2020-01-02", "test", 20)
    assert "known" in result and "future" not in result


def test_macro_never_maps_us_series_or_backfills_history(monkeypatch):
    call = Mock(side_effect=AssertionError)
    monkeypatch.setattr(vendor, "_call", call)
    assert "DATA_UNAVAILABLE" in vendor.get_macro_data("china_cpi", "2020-01-01")
    assert "DATA_UNAVAILABLE" in vendor.get_macro_data("fed_funds_rate", vendor.get_current_date())
    call.assert_not_called()


def test_macro_and_news_accept_optional_tool_none_arguments(monkeypatch):
    date = vendor.get_current_date()
    monkeypatch.setattr(vendor, "_call", Mock(return_value=pd.DataFrame({"TRADE_DATE": [date], "LPR1Y": [3.0]})))
    assert "3.0" in vendor.get_macro_data("china_lpr", date, None)
    monkeypatch.setattr(vendor, "_call", Mock(return_value=pd.DataFrame({"发布时间": [date + " 00:00:00"], "标题": ["domestic"]})))
    assert "domestic" in vendor.get_global_news(date, None, None)


def test_router_retains_order_and_falls_back_to_akshare(monkeypatch):
    from tradingagents.dataflows.router import VENDOR_METHODS, route_to_vendor

    calls = []

    def unavailable(name):
        def run(*args):
            calls.append(name)
            raise VendorUnavailableError(name)
        return run
    monkeypatch.setitem(VENDOR_METHODS, "get_income_statement", {
        "sec_edgar": unavailable("edgar"), "yfinance": unavailable("yahoo"),
        "akshare": lambda *args: calls.append("akshare") or "China financials",
    })
    with run_config({"data_vendors": {"fundamental_data": "sec_edgar,yfinance,akshare"}}):
        assert route_to_vendor("get_income_statement", "600519.SS") == "China financials"
    assert calls == ["edgar", "yahoo", "akshare"]


def test_a_share_limits_dates_before_fetch_and_keeps_ytd_contract(monkeypatch):
    dates = [f"{year}-12-31" for year in range(2000, 2027)] + ["2026-06-30", "2026-09-30", "2099-12-31"]
    session = Mock()
    session.get.side_effect = [
        Mock(text='<input value="1" id="hidctype" />'),
        Mock(json=lambda: {"data": [{"REPORT_DATE": d} for d in dates]}),
        Mock(json=lambda: {"data": [{"REPORT_DATE": "2026-09-30", "CURRENCY": "CNY", "TOTAL_OPERATE_INCOME": 100}]}),
    ]
    monkeypatch.setattr(vendor.requests, "Session", lambda: Mock(__enter__=Mock(return_value=session), __exit__=Mock(return_value=False)))
    frame = vendor._recent_a_statement("stock_profit_sheet_by_report_em", "SH600519", 4, "2026-11-10", "quarterly")
    assert len(frame) == 1 and frame.iloc[0]["CURRENCY"] == "CNY"
    assert session.get.call_count == 3
    last = session.get.call_args.kwargs
    assert last["params"]["dates"] == "2026-09-30,2026-06-30,2025-12-31,2024-12-31"
    assert last["params"]["reportType"] == "1" and last["timeout"] == 10
