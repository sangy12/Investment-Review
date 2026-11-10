"""Acceptance of the wrapper with deterministic graph fixtures, not live LLM claims."""

from types import SimpleNamespace
from unittest.mock import Mock

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


def test_shared_sources_are_prepared_after_factory_and_archived_once(tmp_path, monkeypatch):
    from tradingagents.watchlist import runner

    events = []
    packet = {"schema": 1, "ticker": "NVDA", "as_of": "2026-01-02", "items": [], "gaps": ["fixture gap"], "mcp_calls": 0}

    def prepare(*args):
        events.append("sources")
        return packet

    class SharedGraph(FakeGraph):
        def __init__(self, config):
            events.append("factory")
            super().__init__(config)

        def propagate(self, ticker, date):
            events.append("graph")
            assert "fixture gap" in self.config["shared_research_evidence"]
            return super().propagate(ticker, date)

    monkeypatch.setattr(runner, "prepare_evidence", prepare)
    assert run_batch([POSITION], {"data_vendors": {}, "research_sources": {"enabled": True}},
                     tmp_path, "2026-01-02", graph_factory=SharedGraph, reviewer=review_fixture,
                     on_status=lambda _: None) == []
    assert events == ["factory", "sources", "graph"]
    run = next((tmp_path / "NVDA/runs").iterdir())
    assert (run / "research_sources.json").exists()
    assert "fixture gap" in (run / "complete_report.md").read_text()
    assert "fixture gap" in (run / "complete_report.html").read_text()
    assert history(tmp_path, "NVDA")[0]["source_packet_sha256"]


def test_failed_subscription_factory_cannot_start_paid_sources(tmp_path, monkeypatch):
    from tradingagents.watchlist import runner

    prepare = Mock(side_effect=AssertionError("Must not spend"))
    monkeypatch.setattr(runner, "prepare_evidence", prepare)

    def factory(**kwargs):
        raise RuntimeError("model access not available")

    assert run_batch([POSITION], {"data_vendors": {}, "research_sources": {"enabled": True}},
                     tmp_path, "2026-01-02", graph_factory=factory, on_status=lambda _: None)
    prepare.assert_not_called()


def test_runner_tracks_graph_and_review_and_archives_usage(tmp_path):
    import json

    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    from tradingagents.watchlist.usage import usage_context

    class MeasuredGraph(FakeGraph):
        def __init__(self, config):
            super().__init__(config)
            msg = AIMessage(content="fixture", response_metadata={"model_name": "gpt-6.1-terra"},
                            usage_metadata={"input_tokens": 100, "output_tokens": 30, "total_tokens": 130})
            self.quick_thinking_llm = GenericFakeChatModel(messages=iter([msg, msg]))

        def propagate(self, ticker, date):
            self.quick_thinking_llm.invoke("fixture graph")
            return super().propagate(ticker, date)

    def reviewer(state, position, previous, llm):
        llm.invoke("fixture review")
        return review_fixture(state, position, previous, llm)

    assert run_batch([POSITION], {"data_vendors": {}}, tmp_path, "2026-01-02",
                     graph_factory=MeasuredGraph, reviewer=reviewer, on_status=lambda _: None) == []
    run = next((tmp_path / "NVDA/runs").iterdir())
    data = json.loads((run / "usage.json").read_text())
    assert data["totals"]["total_tokens"] == 260
    assert data["totals"]["completed_calls"] == 2
    assert {r["phase"] for r in data["by_model_and_phase"]} == {"graph", "review"}
    assert "260 token" in (run / "complete_report.md").read_text()
    assert "260 token" in (run / "complete_report.html").read_text()
    assert usage_context.get() is None


def test_usage_context_restored_after_interruption(tmp_path):
    import json

    from tradingagents.watchlist.usage import usage_context

    def factory(**kwargs):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_batch([POSITION], {"data_vendors": {}}, tmp_path, "2026-01-02",
                  graph_factory=factory, on_status=lambda _: None)
    data = json.loads(next((tmp_path / "NVDA/usage").glob("*.json")).read_text())
    assert data["status"] == "interrupted"
    assert usage_context.get() is None


def test_subscription_limit_stops_batch_and_structured_retry(tmp_path):
    import json

    from tradingagents.agents.structured import invoke_structured_or_freetext
    from tradingagents.llm_clients.plan_errors import ChatGPTSubscriptionLimitError

    structured = Mock()
    structured.invoke.side_effect = ChatGPTSubscriptionLimitError()
    plain = Mock()
    called = []

    class LimitedGraph(FakeGraph):
        def propagate(self, ticker, date):
            called.append(ticker)
            invoke_structured_or_freetext(structured, plain, "fixture", str, "Trader")

    failures = run_batch([POSITION, {**POSITION, "ticker": "AAPL"}], {"data_vendors": {}},
                         tmp_path, "2026-01-02", graph_factory=LimitedGraph, on_status=lambda _: None)
    assert called == ["NVDA"]
    structured.invoke.assert_called_once()
    plain.invoke.assert_not_called()
    assert failures[0]["error_code"] == "subscription_usage_limit"
    data = json.loads((tmp_path / "last_batch.json").read_text())
    assert "未执行" in data["outcomes"]["AAPL"]


def test_resume_only_requires_matching_checkpoint_before_inference(tmp_path, monkeypatch):
    import json

    from tradingagents.watchlist import runner

    packet = {"schema": 1, "ticker": "NVDA", "as_of": "2026-01-02", "items": [], "gaps": [], "mcp_calls": 0}
    prepare = Mock(return_value=packet)
    monkeypatch.setattr(runner, "prepare_evidence", prepare)
    propagate = Mock(return_value=(state(), "Hold"))

    class ResumeGraph(FakeGraph):
        step = None

        def checkpoint_resume_step(self, ticker, date):
            return self.step

        def propagate(self, ticker, date):
            return propagate(ticker, date)

    cfg = {"data_vendors": {}, "research_sources": {"enabled": True}}
    assert run_batch([POSITION], cfg, tmp_path, "2026-01-02", graph_factory=ResumeGraph,
                     reviewer=review_fixture, on_status=lambda _: None, resume_only=True)
    propagate.assert_not_called()
    assert prepare.call_args.kwargs == {"cached_only": True}
    ResumeGraph.step = 6
    assert not run_batch([POSITION], cfg, tmp_path, "2026-01-02", graph_factory=ResumeGraph,
                         reviewer=review_fixture, on_status=lambda _: None, resume_only=True)
    propagate.assert_called_once()
    run = next((tmp_path / "NVDA/runs").iterdir())
    assert json.loads((run / "usage.json").read_text())["resumed_from_step"] == 6
