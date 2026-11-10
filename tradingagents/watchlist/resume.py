"""Recover the original research packet only from a matching saved graph."""

import json
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from tradingagents.dataflows.symbols import safe_ticker_component
from tradingagents.graph.checkpointer import thread_id
from tradingagents.watchlist.evidence import render_evidence


def checkpoint_packet(graph, position, date):
    """Keep transient retrieval gaps from changing a resumed graph's inputs.

    The saved ticker/date, packet and entire run signature must all match.
    No current data is fetched or substituted into a historical checkpoint.
    """
    cfg = graph.config
    if not cfg.get("checkpoint_enabled") or not cfg.get("data_cache_dir"):
        return None
    path = Path(cfg["data_cache_dir"]) / "checkpoints" / (safe_ticker_component(position["ticker"]).upper() + ".db")
    if not path.exists():
        return None
    missing = object()
    original = cfg.get("shared_research_evidence", missing)
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
            rows = conn.execute("SELECT thread_id, MAX(checkpoint_id) FROM checkpoints "
                                "WHERE checkpoint_ns='' GROUP BY thread_id "
                                "ORDER BY MAX(checkpoint_id) DESC LIMIT 100").fetchall()
            saver = SqliteSaver(conn)
            for saved_thread, checkpoint_id in rows:
                cp = saver.get_tuple({"configurable": {"thread_id": saved_thread, "checkpoint_ns": "",
                                                       "checkpoint_id": checkpoint_id}})
                if cp is None:
                    continue
                state = cp.checkpoint.get("channel_values", {})
                if state.get("company_of_interest") != position["ticker"] or state.get("trade_date") != date:
                    continue
                context = state.get("instrument_context", "")
                marker = "\n\n## 共享来源材料\n"
                if not isinstance(context, str) or marker not in context or len(context) > 250000:
                    continue
                saved = "## 共享来源材料\n" + context.split(marker, 1)[1]
                body = saved.partition("```json\n")[2].rpartition("\n```")[0]
                try:
                    packet = json.loads(body)
                except (ValueError, TypeError):
                    continue
                if not isinstance(packet, dict) or packet.get("ticker") != position["ticker"] or packet.get("as_of") != date:
                    continue
                if not isinstance(packet.get("items"), list) or not isinstance(packet.get("gaps"), list):
                    continue
                packet["mcp_calls"] = 0  # No new paid requests in this resume.
                if render_evidence(packet) != saved:
                    continue
                cfg["shared_research_evidence"] = saved
                if thread_id(position["ticker"], date, graph._run_signature("stock")) == saved_thread:
                    return packet
    except sqlite3.Error:
        return None
    finally:
        if original is missing:
            cfg.pop("shared_research_evidence", None)
        else:
            cfg["shared_research_evidence"] = original
    return None
