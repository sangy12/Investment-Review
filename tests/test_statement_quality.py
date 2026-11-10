import json

import pytest

from tradingagents.dataflows import statement_quality as sq
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.router import VENDOR_METHODS, route_to_vendor
from tradingagents.watchlist.config import load_config, market_config


def table(period, value=100):
    return f"# Company statement\n,{period}\nRevenue,{value}\n"


@pytest.fixture
def policy(monkeypatch):
    monkeypatch.setattr(sq, "is_historical", lambda _: False)
    return {"enabled": True, "compare_markets": ["HK", "A_SHARE"],
            "max_age_days": {"HK": 275, "A_SHARE": 160, "US": 275}}


def test_market_priorities_are_independent_and_do_not_mutate_profile():
    cfg = load_config("config/redteam.yaml")
    cfg["market_tool_vendors"]["A_SHARE"]["get_cashflow"] = "akshare"
    hk = market_config(cfg, {"market": "HK"})
    ashare = market_config(cfg, {"market": "A_SHARE"})
    us = market_config(cfg, {"market": "US"})
    assert hk["tool_vendors"]["get_cashflow"] == "akshare,yfinance"
    assert ashare["tool_vendors"]["get_cashflow"] == "akshare"
    assert "get_cashflow" not in us["tool_vendors"]
    assert us["data_vendors"]["fundamental_data"] == "sec_edgar,yfinance"
    assert "market_tool_vendors" in cfg


def test_old_nonempty_yahoo_table_does_not_hide_newer_fallback(monkeypatch, policy):
    calls = []
    monkeypatch.setitem(VENDOR_METHODS, "get_cashflow", {
        "yfinance": lambda *args: calls.append("yahoo") or table("2025-12-31"),
        "akshare": lambda *args: calls.append("akshare") or "REPORT_DATE,AMOUNT\n2026-06-30,123\n",
    })
    with run_config({"tool_vendors": {"get_cashflow": "yfinance,akshare"}, "statement_freshness": policy}):
        result = route_to_vendor("get_cashflow", "0100.HK", "quarterly", "2026-11-10")
    assert calls == ["yahoo", "akshare"]
    assert '"vendor": "akshare"' in result and '"latest_period": "2026-06-30"' in result
    assert '"latest_period": "2025-12-31"' in result and '"status": "rejected"' in result
    assert "Revenue,100" not in result and "123" in result


def test_comparison_picks_newest_and_priority_breaks_ties(monkeypatch, policy):
    monkeypatch.setitem(VENDOR_METHODS, "get_income_statement", {
        "akshare": lambda *args: table("2026-06-30", 100),
        "yfinance": lambda *args: table("2026-09-30", 999),
    })
    cfg = {"tool_vendors": {"get_income_statement": "akshare,yfinance"}, "statement_freshness": policy}
    with run_config(cfg):
        result = route_to_vendor("get_income_statement", "0700.HK", "quarterly", "2026-11-10")
    assert '"vendor": "yfinance"' in result and "Revenue,999" in result
    monkeypatch.setitem(VENDOR_METHODS["get_income_statement"], "yfinance", lambda *a: table("2026-06-30", 999))
    with run_config(cfg):
        result = route_to_vendor("get_income_statement", "0700.HK", "quarterly", "2026-11-10")
    assert '"vendor": "akshare"' in result and "Revenue,100" in result and "Revenue,999" not in result


def test_no_guess_of_hk_q3_or_annual_interim_comparability(policy):
    args = ("0100.HK", "quarterly", "2026-11-10")
    p = sq.policy_for("get_cashflow", args, {}, {"statement_freshness": policy})
    assert sq.assess(table("2026-06-30"), "fixture", p)["latest_period"] == "2026-06-30"
    p["frequency"] = "annual"
    assert sq.assess(table("2025-12-31"), "fixture", p)["latest_period"] == "2025-12-31"


def test_official_report_period_is_a_floor_only_for_nonannual_calls(policy):
    items = [{"source": "HKEX issuer filing", "financial_report": True, "period": "2026-06-30"}]
    cfg = {"statement_freshness": policy, "shared_research_evidence": "```json\n" + json.dumps({"items": items}) + "\n```\n"}
    p = sq.policy_for("get_cashflow", ("0100.HK", "quarterly", "2026-08-01"), {}, cfg)
    with pytest.raises(sq.NoMarketDataError, match="precedes official"):
        sq.assess(table("2025-12-31"), "fixture", p)
    p = sq.policy_for("get_cashflow", ("0100.HK", "annual", "2026-11-10"), {}, cfg)
    assert "official_reference_period" not in p


def test_future_and_undated_tables_are_rejected_without_retrieval_date_confusion(policy):
    p = sq.policy_for("get_cashflow", ("0100.HK", "quarterly", "2026-11-10"), {}, {"statement_freshness": policy})
    for text in [table("2099-01-01"), "# retrieved 2026-11-10\nitem,amount\ncash,999\n"]:
        with pytest.raises(sq.NoMarketDataError):
            sq.assess(text, "fixture", p)


def test_empty_latest_period_is_not_mistaken_for_new_financial_data():
    wide = ",2026-09-30,2026-06-30\nRevenue,,100\nCash,,200\n"
    long = "REPORT_DATE,AMOUNT\n2026-09-30,\n2026-06-30,100\n"
    assert sq.statement_periods(wide) == ["2026-06-30"]
    assert sq.statement_periods(long) == ["2026-06-30"]


def test_historical_run_keeps_as_filed_routing(monkeypatch, policy):
    monkeypatch.setattr(sq, "is_historical", lambda _: True)
    assert sq.policy_for("get_cashflow", ("NVDA", "quarterly", "2020-01-01"), {}, {"statement_freshness": policy}) is None


def test_hk_contract_is_cny_not_hkd_or_issuer_usd(monkeypatch):
    import pandas as pd

    from tradingagents.dataflows.vendors import akshare

    monkeypatch.setattr(akshare, "_withheld", lambda *a: None)
    monkeypatch.setattr(akshare, "_call", lambda *a, **kw: pd.DataFrame({"REPORT_DATE": ["2026-06-30"], "AMOUNT": [793967045.7]}))
    out = akshare.get_income_statement("0100.HK", as_of_date="2026-11-10")
    assert "monetary amount currency: CNY" in out and "not issuer currency" in out
    assert "793967045.7" in out
