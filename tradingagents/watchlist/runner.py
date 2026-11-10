"""Batch execution with immutable runs and a rebuildable current index."""

import hashlib
import json
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from markdown_it import MarkdownIt

from tradingagents.agents.rating import run_rating
from tradingagents.dataflows.files import locked
from tradingagents.llm_clients.plan_errors import ChatGPTSubscriptionLimitError
from tradingagents.reporting import write_report_tree
from tradingagents.watchlist.config import market_config, today, validate_date
from tradingagents.watchlist.evidence import prepare_evidence, render_evidence
from tradingagents.watchlist.resume import checkpoint_packet
from tradingagents.watchlist.review import changes, make_review, summary_markdown, validate_complete
from tradingagents.watchlist.usage import UsageTracker, usage_context, usage_markdown


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def history(root, ticker, as_of=None):
    runs = []
    for path in (Path(root) / ticker / "runs").glob("*/snapshot.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if as_of is None or data["date"] <= as_of:
            runs.append(data)
    return sorted(runs, key=lambda r: (r["date"], r["created_at"], r["run_id"]))


def fingerprint(position, date, cfg):
    # Hash only, never persist credentials or endpoint configuration.
    return hashlib.sha256(json.dumps({"position": position, "date": date, "config": cfg,
                                      "review_schema": 1}, sort_keys=True, default=str).encode()).hexdigest()


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ").replace("<", "&lt;")


def write_index(root, positions, outcomes):
    lines = ["# 持仓研究索引", "", "| 标的 | 分析日期 | 当前评级 | 较上次变化 | 失效条件命中/总数（证据不足） | 本次状态 | 报告 |",
             "|---|---|---|---|---|---|---|"]
    for position in positions:
        ticker = position["ticker"]
        runs = history(root, ticker)
        state = outcomes.get(ticker, "本批次未选中")
        if not runs:
            lines.append(f"| {ticker} {_cell(position['name'])} | — | — | — | — | {_cell(state)} | — |")
            continue
        current = runs[-1]
        previous = next((r for r in runs if r["run_id"] == current["previous_run_id"]), None)
        checks = current["review"]["checks"]
        hit = sum(c["status"] == "triggered" for c in checks)
        unknown = sum(c["status"] == "unknown" for c in checks)
        count = f"{hit}/{len(checks)}（{unknown}）" if checks else "无核对基准"
        lines.append(f"| {ticker} {_cell(position['name'])} | {current['date']} | {current['rating']} | "
                     f"{changes(current, previous)['rating']} | {count} | {_cell(state)} | "
                     f"[Markdown]({ticker}/{current['date']}.md) · [HTML]({ticker}/runs/{current['run_id']}/complete_report.html) |")
    atomic_text(Path(root) / "index.md", "\n".join(lines) + "\n")


def run_batch(positions, cfg, root="reports", date=None, only=None, skip_unchanged=False,
              graph_factory=None, reviewer=make_review, on_status=print, resume_only=False):
    date = validate_date(date or today())
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if only:
        only = only.upper()
        if not any(p["ticker"] == only for p in positions):
            raise ValueError(f"清单中没有标的 {only}")
    outcomes = {}
    failures = []
    # One batch owns canonical aliases/index; graph's own checkpoint locks still apply.
    with locked(root / ".batch"):
        try:
            for position_index, position in enumerate(positions):
                ticker = position["ticker"]
                if only and ticker != only:
                    continue
                effective = market_config(cfg, position)
                signature = fingerprint(position, date, effective)
                prior = history(root, ticker, date)
                if skip_unchanged and prior and prior[-1]["date"] == date and prior[-1]["fingerprint"] == signature:
                    outcomes[ticker] = "已跳过：同日期及输入已有成功运行"
                    on_status(f"{ticker}: {outcomes[ticker]}")
                    continue
                run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
                staging = root / ticker / "runs" / f".pending-{run_id}"
                usage = UsageTracker(root / ticker / "usage" / f"{run_id}.json")
                usage_token = usage_context.set(usage)
                try:
                    on_status(f"{ticker}: 开始完整分析 {date}")
                    if graph_factory is None:
                        from tradingagents.graph.trading_graph import TradingAgentsGraph

                        factory = TradingAgentsGraph
                    else:
                        factory = graph_factory
                    graph = factory(config=effective)
                    packet = None
                    if effective.get("research_sources", {}).get("enabled"):
                        # Factory verifies subscription/model access before any paid
                        # data is fetched. Every agent receives this same packet.
                        packet = checkpoint_packet(graph, position, date) if resume_only else None
                        if packet is None:
                            packet = (prepare_evidence(position, date, effective, cached_only=True) if resume_only
                                      else prepare_evidence(position, date, effective))
                        effective["shared_research_evidence"] = render_evidence(packet)
                        graph.config["shared_research_evidence"] = effective["shared_research_evidence"]
                    checker = getattr(graph, "checkpoint_resume_step", None)
                    step = checker(ticker, date) if callable(checker) else None
                    usage.resumed_from_step = step if type(step) is int else None
                    if resume_only and usage.resumed_from_step is None:
                        raise ValueError("没有匹配当前配置和材料的断点；未发起模型调用。")
                    state, _ = graph.propagate(ticker, date)
                    # Retain the graph's complete output even if review extraction fails.
                    settings = graph.run_settings()
                    write_report_tree(state, ticker, staging, settings=settings)
                    if packet is not None:
                        atomic_text(staging / "research_sources.json", json.dumps(packet, ensure_ascii=False, indent=2))
                        atomic_text(staging / "research_sources.md", render_evidence(packet))
                    validate_complete(state)
                    previous = prior[-1] if prior else None
                    usage.phase = "review"
                    review = reviewer(state, position, previous, graph.quick_thinking_llm)
                    usage.finish("completed")
                    usage_data = usage.snapshot()
                    atomic_text(staging / "usage.json", json.dumps(usage_data, ensure_ascii=False, indent=2))
                    snapshot = {"schema_version": 1, "run_id": run_id, "date": date,
                                "created_at": datetime.now(UTC).isoformat(), "ticker": ticker,
                                "position": position, "rating": run_rating(state), "review": review,
                                "fingerprint": signature,
                                "previous_run_id": previous["run_id"] if previous else None,
                                "settings": settings, "usage": usage_data}
                    if packet is not None:
                        snapshot["source_packet_sha256"] = hashlib.sha256(
                            render_evidence(packet).encode()).hexdigest()
                    summary = summary_markdown(snapshot, previous) + "\n" + usage_markdown(usage_data)
                    original = (staging / "complete_report.md").read_text(encoding="utf-8")
                    (staging / "original_report.md").write_text(original, encoding="utf-8")
                    complete = f"# {ticker} · {date}\n\n" + summary + "\n" + original
                    if packet is not None:
                        complete += "\n\n" + render_evidence(packet)
                    (staging / "complete_report.md").write_text(complete, encoding="utf-8")
                    html_path = staging / "complete_report.html"
                    html = html_path.read_text(encoding="utf-8")
                    rendered = MarkdownIt("commonmark", {"html": False}).render(summary)
                    html_path.write_text(html.replace("<main>", "<main>\n" + rendered, 1), encoding="utf-8")
                    if packet is not None:
                        html = html_path.read_text(encoding="utf-8")
                        rendered_sources = MarkdownIt("commonmark", {"html": False}).render(render_evidence(packet))
                        html_path.write_text(html.replace("</main>", rendered_sources + "</main>", 1), encoding="utf-8")
                    (staging / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
                    final = staging.with_name(run_id)
                    staging.rename(final)  # success marker: only committed runs enter history
                    # Immutable history is authoritative; aliases can be rebuilt from it.
                    canonical = root / ticker / date
                    canonical.mkdir(exist_ok=True)
                    atomic_text(root / ticker / f"{date}.md", complete)
                    atomic_text(canonical / "complete_report.html", (final / "complete_report.html").read_text(encoding="utf-8"))
                    atomic_text(canonical / "snapshot.json", (final / "snapshot.json").read_text(encoding="utf-8"))
                    outcomes[ticker] = "成功"
                    on_status(f"{ticker}: 成功，{root / ticker / (date + '.md')}")
                except Exception as exc:
                    usage.finish("failed")
                    # Error strings can contain signed URLs/auth headers: persist only the type.
                    outcomes[ticker] = f"失败：{type(exc).__name__}；已有报告可能较旧"
                    failures.append({"ticker": ticker, "error_type": type(exc).__name__})
                    if isinstance(exc, ChatGPTSubscriptionLimitError):
                        failures[-1]["error_code"] = exc.code
                        outcomes[ticker] = "失败：ChatGPT 订阅共享额度已达上限；保留断点，待额度重置"
                    if staging.exists():
                        failed_path = root / ticker / "failed" / run_id
                        failed_path.parent.mkdir(parents=True, exist_ok=True)
                        staging.rename(failed_path)
                    on_status(f"{ticker}: {outcomes[ticker]}")
                    if isinstance(exc, ChatGPTSubscriptionLimitError):
                        for pending in positions[position_index + 1:]:
                            if not only or pending["ticker"] == only:
                                outcomes[pending["ticker"]] = "未执行：ChatGPT 订阅共享额度已达上限"
                        break
                finally:
                    if usage.snapshot()["status"] == "running":
                        usage.finish("interrupted")
                    usage_context.reset(usage_token)
                    shutil.rmtree(staging, ignore_errors=True)
        finally:
            write_index(root, positions, outcomes)
            atomic_text(root / "last_batch.json", json.dumps({"date": date, "outcomes": outcomes, "failures": failures}, ensure_ascii=False, indent=2))
    return failures


def compare_report(root, ticker):
    # Reuse ticker/path validation without touching the user's current watchlist.
    import re

    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.^=-]{0,30}", ticker):
        raise ValueError("ticker 非法")
    runs = history(root, ticker)
    if not runs:
        raise ValueError(f"{ticker}: 没有成功报告")
    current = runs[-1]
    previous = next((r for r in runs if r["run_id"] == current["previous_run_id"]), None)
    trajectory = " → ".join(f"{r['date']} ({r['run_id']}): {r['rating']}" for r in runs)
    return f"# {ticker} 对照\n\n评级轨迹：{trajectory}\n\n" + summary_markdown(current, previous)
