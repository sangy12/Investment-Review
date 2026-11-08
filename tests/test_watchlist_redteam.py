"""Acceptance of the wrapper with deterministic graph fixtures, not live LLM claims."""

from types import SimpleNamespace

import pytest
import yaml

from tradingagents.watchlist.config import load_config, load_positions, market_config
from tradingagents.watchlist.review import Review, make_review
from tradingagents.watchlist.runner import compare_report, history, run_batch

POSITION = {"ticker": "NVDA", "name": "NVIDIA", "market": "US", "thesis": "长期需求"}


def state(rating="Hold"):
    return {
        "trade_date": "2026-01-02", "market_report": "price 100", "sentiment_report": "unknown",
        "news_report": "Demand fell 20%.", "fundamentals_report": "Revenue USD 100, FY2025.",
        "investment_debate_state": {"bull_history": "Durable moat.", "bear_history": "Demand risk."},
        "investment_plan": "Hold for evidence.", "trader_investment_plan": "Entry 100; stop 90; size 5%.",
        "risk_debate_state": {"aggressive_history": "Upside risk.", "conservative_history": "Demand risk.", "neutral_history": "Size conservatively."},
        "final_trade_decision": f"**Rating**: {rating}\n\n**Investment Thesis**: Durable moat. What would change it: demand falls 20%.",
        "final_rating": rating,
    }


def review_fixture(current, position, previous, llm):
    return {"thesis": [{"text": "护城河", "evidence": [{"source": "5_portfolio/decision.md", "quote": "Durable moat."}]}],
            "risks": [{"text": "需求风险", "evidence": []}],
            "conditions": [{"text": "demand falls 20%", "evidence": []}],
            "checks": [{"condition": c["text"], "status": "triggered", "explanation": "需求下降", "evidence": [{"source": "1_analysts/news.md", "quote": "Demand fell 20%."}]} for c in (previous or {}).get("review", {}).get("conditions", [])],
            "variables": [{"name": "Revenue FY2025", "value": "USD 100", "evidence": []}],
            "user_thesis_check": "需求风险需进一步验证"}


class FakeGraph:
    calls = []
    rating = "Hold"

    def __init__(self, config):
        self.config = config
        self.quick_thinking_llm = None

    def propagate(self, ticker, date):
        self.calls.append((ticker, date))
        return state(self.rating), self.rating

    def run_settings(self):
        return {"version": "0.7.1", "llm_provider": "chatgpt"}


@pytest.fixture
def batch(tmp_path):
    FakeGraph.calls = []
    FakeGraph.rating = "Hold"

    def run(positions=None, date="2026-01-02", **kwargs):
        return run_batch(positions if positions is not None else [POSITION], {"data_vendors": {}},
                         tmp_path, date, graph_factory=FakeGraph, reviewer=review_fixture,
                         on_status=lambda _: None, **kwargs)
    return run


def test_batch_complete_reports_same_day_history_and_skip(batch, tmp_path):
    assert batch() == []
    first = history(tmp_path, "NVDA")[0]
    text = (tmp_path / "NVDA/2026-01-02.md").read_text()
    for expected in ("评级", "投资逻辑摘要", "风险清单", "与上次运行的变化", "Entry 100; stop 90; size 5%.", "Durable moat."):
        assert expected in text
    assert "长期投资红队摘要" in (tmp_path / "NVDA/2026-01-02/complete_report.html").read_text()
    FakeGraph.rating = "Sell"
    assert batch() == []
    runs = history(tmp_path, "NVDA")
    assert len(runs) == 2 and runs[-1]["previous_run_id"] == first["run_id"]
    report = compare_report(tmp_path, "NVDA")
    assert "Hold → Sell" in report and "[触发] demand falls 20%" in report
    assert "1/1（0）" in (tmp_path / "index.md").read_text()
    assert batch(skip_unchanged=True) == []
    assert len(FakeGraph.calls) == 2
    # A changed personal thesis invalidates the skip key.
    assert batch([{**POSITION, "thesis": "新论点"}], skip_unchanged=True) == []
    assert len(FakeGraph.calls) == 3


def test_backfill_does_not_read_future_thesis(batch, tmp_path):
    batch(date="2026-01-05")
    batch(date="2026-01-01")
    early = history(tmp_path, "NVDA", "2026-01-01")[0]
    assert early["previous_run_id"] is None
    assert early["review"]["checks"] == []


def test_failure_continues_batch_and_retains_previous_report(batch, tmp_path, monkeypatch):
    batch()
    original = (tmp_path / "NVDA/2026-01-02.md").read_text()
    original_propagate = FakeGraph.propagate

    def failing(self, ticker, date):
        if ticker == "NVDA":
            raise RuntimeError("secret=must-not-be-persisted")
        return original_propagate(self, ticker, date)
    monkeypatch.setattr(FakeGraph, "propagate", failing)
    other = {**POSITION, "ticker": "AAPL"}
    failures = batch([POSITION, other])
    assert len(failures) == 1
    assert len(history(tmp_path, "AAPL")) == 1
    assert (tmp_path / "NVDA/2026-01-02.md").read_text() == original
    assert "secret=" not in (tmp_path / "last_batch.json").read_text()
    assert "失败" in (tmp_path / "index.md").read_text()


def test_only_remove_and_empty_watchlist_rebuild_index(batch, tmp_path):
    batch([POSITION, {**POSITION, "ticker": "AAPL"}], only="aapl")
    assert FakeGraph.calls == [("AAPL", "2026-01-02")]
    batch([])
    assert "AAPL" not in (tmp_path / "index.md").read_text()
    assert history(tmp_path, "AAPL")  # removing a position does not delete research
    with pytest.raises(ValueError):
        batch(only="MSFT")


def test_invalid_rating_is_failed_not_hold(batch, tmp_path, monkeypatch):
    monkeypatch.setattr(FakeGraph, "rating", "REVIEW")
    assert batch()[0]["error_type"] == "ValueError"
    assert history(tmp_path, "NVDA") == []
    assert list((tmp_path / "NVDA/failed").glob("*/complete_report.md"))


def test_injected_auth_seed_never_overwrites_rotated_tokens(tmp_path, monkeypatch):
    import json

    from tradingagents.llm_clients import chatgpt_auth
    from tradingagents.watchlist.auth import bootstrap_auth

    target = tmp_path / "store/chatgpt-auth.json"
    monkeypatch.setattr(chatgpt_auth, "AUTH_FILE", target)
    seed = tmp_path / "secret.json"
    data = {"host_id": "test-host", "account": {"client_id": "client"}, "tokens": {"access_token": "test-access", "refresh_token": "test-refresh"}}
    seed.write_text(json.dumps(data))
    bootstrap_auth(seed)
    assert target.stat().st_mode & 0o777 == 0o600
    data["tokens"]["refresh_token"] = "rotated"
    chatgpt_auth._write(data)
    bootstrap_auth(seed)
    assert chatgpt_auth._read()["tokens"]["refresh_token"] == "rotated"


def test_review_rejects_fabricated_citations_and_checks_missing_evidence():
    payload = review_fixture(state(), POSITION, None, None)
    payload["thesis"][0]["evidence"][0]["quote"] = "invented evidence"
    payload["checks"] = [{"condition": "demand falls 20%", "status": "not_triggered", "explanation": "No evidence", "evidence": []}]
    previous = {"review": {"conditions": [{"text": "demand falls 20%"}, {"text": "moat lost"}]}}
    llm = SimpleNamespace(with_structured_output=lambda _: SimpleNamespace(invoke=lambda _: Review.model_validate(payload)))
    result = make_review(state(), POSITION, previous, llm)
    assert result["thesis"] == []
    assert [c["status"] for c in result["checks"]] == ["unknown", "unknown"]


@pytest.mark.parametrize("rows", [
    [{**POSITION, "ticker": "../../escape"}], [POSITION, POSITION],
    [{**POSITION, "ticker": "600519.SS"}],
    [{**POSITION, "ticker": "0700.HK", "market": "HK"}, {**POSITION, "ticker": "00700.HK", "market": "HK"}],
])
def test_watchlist_validation(tmp_path, rows):
    path = tmp_path / "watchlist.yaml"
    path.write_text(yaml.safe_dump({"positions": rows}))
    with pytest.raises(ValueError):
        load_positions(path)


def test_profile_env_precedence_and_subscription_knobs(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("llm_provider: chatgpt\nmax_risk_discuss_rounds: 2\n")
    monkeypatch.setenv("TRADINGAGENTS_MAX_RISK_DISCUSS_ROUNDS", "3")
    cfg = load_config(path)
    assert cfg["max_risk_discuss_rounds"] == 3
    assert "temperature" not in cfg and "max_tokens" not in cfg
    monkeypatch.setenv("TRADINGAGENTS_TEMPERATURE", "0.2")
    with pytest.raises(ValueError, match="temperature"):
        load_config(path)


def test_china_vendor_routing_is_market_scoped():
    cfg = {"data_vendors": {"fundamental_data": "sec_edgar,yfinance"}, "china_data_vendors": {"fundamental_data": "sec_edgar,yfinance,akshare"}}
    assert market_config(cfg, POSITION)["data_vendors"]["fundamental_data"] == "sec_edgar,yfinance"
    china = market_config(cfg, {"market": "HK"})
    assert china["data_vendors"]["fundamental_data"] == "sec_edgar,yfinance,akshare"
    assert cfg["data_vendors"]["fundamental_data"] == "sec_edgar,yfinance"
