"""Restore saved evidence without silently restarting a different graph."""

from copy import deepcopy

from langgraph.checkpoint.base import empty_checkpoint

from tradingagents.graph.checkpointer import get_checkpointer, thread_id
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.watchlist.evidence import render_evidence
from tradingagents.watchlist.resume import checkpoint_packet

POSITION = {"ticker": "600519.SS", "market": "A_SHARE", "name": "茅台", "thesis": ""}
DATE = "2026-01-02"


def saved_graph(tmp_path, *, packet_date=DATE):
    graph = object.__new__(TradingAgentsGraph)
    graph.config = {"checkpoint_enabled": True, "data_cache_dir": str(tmp_path),
                    "deep_think_llm": "gpt-6.1-sol", "max_debate_rounds": 2, "max_risk_discuss_rounds": 2}
    graph.selected_analysts = ("market", "news")
    packet = {"schema": 1, "ticker": POSITION["ticker"], "as_of": packet_date, "items": [],
              "gaps": ["报告期发现失败：TimeoutExpired；不发付费查询。"], "mcp_calls": 0}
    graph.config["shared_research_evidence"] = render_evidence(packet)
    tid = thread_id(POSITION["ticker"], DATE, graph._run_signature("stock"))
    cp = empty_checkpoint()
    cp["channel_values"] = {"company_of_interest": POSITION["ticker"], "trade_date": DATE,
                            "instrument_context": "original identity\n\n" + render_evidence(packet)}
    with get_checkpointer(tmp_path, POSITION["ticker"]) as saver:
        saver.put({"configurable": {"thread_id": tid, "checkpoint_ns": ""}}, cp,
                  {"source": "loop", "step": 6, "parents": {}}, {})
    graph.config.pop("shared_research_evidence")
    return graph, packet


def test_recover_original_transient_gap_and_matching_step(tmp_path):
    graph, packet = saved_graph(tmp_path)
    before = deepcopy(graph.config)
    recovered = checkpoint_packet(graph, POSITION, DATE)
    assert recovered == packet
    assert graph.config == before  # Inspection alone does not change run inputs.
    graph.config["shared_research_evidence"] = render_evidence(recovered)
    assert graph.checkpoint_resume_step(POSITION["ticker"], DATE) == 6


def test_model_date_and_packet_date_mismatches_are_rejected(tmp_path):
    graph, _ = saved_graph(tmp_path)
    assert checkpoint_packet(graph, POSITION, "2026-01-03") is None
    graph.config["deep_think_llm"] = "gpt-6-sol"
    before = deepcopy(graph.config)
    assert checkpoint_packet(graph, POSITION, DATE) is None
    assert graph.config == before
    other, _ = saved_graph(tmp_path / "different", packet_date="2026-01-03")
    assert checkpoint_packet(other, POSITION, DATE) is None
