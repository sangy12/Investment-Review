"""Each model tier can name its own provider (#1440).

The quick tier (analysts, researchers, debaters, trader) and the deep tier
(research and portfolio managers) default to ``llm_provider``. A tier that names
another provider gets that provider's own settings and endpoint, never the main
provider's URL, and the run's settings and report say which provider each used.
"""

import pytest

from tradingagents import default_config
from tradingagents.llm_clients import factory


def _config(**overrides):
    config = {**default_config.DEFAULT_CONFIG, "llm_provider": "openai", "backend_url": "https://api.openai.com/v1",
              "quick_think_llm": "gpt-6-luna", "deep_think_llm": "gpt-6-sol",
              "openai_reasoning_effort": "low", "google_thinking_level": "high"}
    config.update(overrides)
    return config


def _captured(monkeypatch):
    made = []
    monkeypatch.setattr(factory, "create_llm_client",
                        lambda provider, model, base_url=None, **kw: made.append((provider, model, base_url, kw)))
    return made


@pytest.mark.unit
def test_a_tier_without_its_own_provider_uses_the_run_s(monkeypatch):
    made = _captured(monkeypatch)

    factory.create_tier_client(_config(), "deep")

    provider, model, base_url, kw = made[0]
    assert (provider, model, base_url) == ("openai", "gpt-6-sol", "https://api.openai.com/v1")
    assert kw["reasoning_effort"] == "low"


@pytest.mark.unit
def test_a_tier_on_another_provider_gets_that_provider_s_settings_and_not_the_main_url(monkeypatch):
    made = _captured(monkeypatch)

    factory.create_tier_client(_config(deep_think_provider="google", deep_think_llm="gemini-3.8-flash"), "deep")

    provider, model, base_url, kw = made[0]
    assert (provider, model) == ("google", "gemini-3.8-flash")
    assert base_url is None                       # the OpenAI URL must not follow it
    assert kw["thinking_level"] == "high" and "reasoning_effort" not in kw


@pytest.mark.unit
def test_a_tier_url_is_used_for_that_tier_only(monkeypatch):
    made = _captured(monkeypatch)
    config = _config(quick_think_provider="openai_compatible", quick_think_backend_url="http://localhost:8000/v1",
                     quick_think_llm="local-model")

    factory.create_tier_client(config, "quick")
    factory.create_tier_client(config, "deep")

    assert made[0][:3] == ("openai_compatible", "local-model", "http://localhost:8000/v1")
    assert made[1][:3] == ("openai", "gpt-6-sol", "https://api.openai.com/v1")


@pytest.mark.unit
def test_the_run_settings_and_report_name_each_tier_s_provider():
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.reporting import _header

    graph = object.__new__(TradingAgentsGraph)
    graph.selected_analysts = ("market",)
    graph.config = _config(deep_think_provider="anthropic", deep_think_llm="claude-opus-5-5")

    settings = graph.run_settings()
    assert settings["quick_think_provider"] == "openai" and settings["deep_think_provider"] == "anthropic"
    header = _header("NVDA", {}, settings)
    assert "deep anthropic claude-opus-5-5" in header and "quick openai gpt-6-luna" in header


@pytest.mark.unit
def test_the_tier_settings_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_DEEP_THINK_PROVIDER", "anthropic")
    monkeypatch.setenv("TRADINGAGENTS_QUICK_THINK_BACKEND_URL", "http://localhost:8000/v1")

    config = default_config.build_default_config()

    assert config["deep_think_provider"] == "anthropic"
    assert config["quick_think_backend_url"] == "http://localhost:8000/v1"
    assert config["quick_think_provider"] is None


def test_reasoning_effort_is_separate_for_each_tier_and_falls_back(monkeypatch):
    made = _captured(monkeypatch)
    cfg = _config(quick_think_llm="gpt-6.1-sol", deep_think_llm="gpt-6.1-sol",
                  quick_think_reasoning_effort="high", deep_think_reasoning_effort="max")
    factory.create_tier_client(cfg, "quick")
    factory.create_tier_client(cfg, "deep")
    assert [row[3]["reasoning_effort"] for row in made] == ["high", "max"]
    cfg["deep_think_reasoning_effort"] = None
    factory.create_tier_client(cfg, "deep")
    assert made[-1][3]["reasoning_effort"] == "low"


def test_tier_effort_environment_overrides(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_QUICK_THINK_REASONING_EFFORT", "high")
    monkeypatch.setenv("TRADINGAGENTS_DEEP_THINK_REASONING_EFFORT", "max")
    cfg = default_config.build_default_config()
    assert cfg["quick_think_reasoning_effort"] == "high"
    assert cfg["deep_think_reasoning_effort"] == "max"


def test_real_subscription_payload_carries_the_selected_effort_without_requests(monkeypatch):
    from langchain_core.messages import HumanMessage

    from tradingagents.llm_clients import chatgpt_auth
    from tradingagents.watchlist.config import load_config

    monkeypatch.setattr(chatgpt_auth, "credential", lambda: lambda: "fixture-token")
    cfg = load_config("config/redteam.yaml")
    for tier, expected in [("quick", "high"), ("deep", "max")]:
        llm = factory.create_tier_client(cfg, tier).get_llm()
        assert llm.model_name == "gpt-6.1-sol"
        payload = llm._get_request_payload([HumanMessage("fixture")])
        assert payload["reasoning"]["effort"] == expected


def test_report_settings_include_the_effective_tier_efforts():
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.reporting import _header

    graph = object.__new__(TradingAgentsGraph)
    graph.selected_analysts = ("market",)
    graph.config = _config(quick_think_reasoning_effort="high", deep_think_reasoning_effort="max")
    settings = graph.run_settings()
    assert settings["deep_think_reasoning_effort"] == "max"
    assert settings["quick_think_reasoning_effort"] == "high"
    assert "Reasoning effort: deep max, quick high" in _header("NVDA", {}, settings)


def test_unset_tier_overrides_preserve_existing_checkpoint_signature():
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.selected_analysts = ("market",)
    graph.config = _config(quick_think_reasoning_effort=None, deep_think_reasoning_effort=None)
    before = graph._run_signature("stock")
    graph.config.pop("quick_think_reasoning_effort")
    graph.config.pop("deep_think_reasoning_effort")
    assert graph._run_signature("stock") == before
    graph.config["deep_think_reasoning_effort"] = "max"
    assert graph._run_signature("stock") != before
