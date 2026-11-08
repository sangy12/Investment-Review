from pathlib import Path
from typing import Annotated

import typer

from tradingagents.watchlist.config import load_config, load_positions
from tradingagents.watchlist.runner import compare_report, run_batch

app = typer.Typer(help="基本面长期投资红队与清单跟踪（仅研究）", no_args_is_help=True,
                  pretty_exceptions_enable=False)


def _auth_error(exc):
    from tradingagents.llm_clients.chatgpt_auth import ChatGPTAuthError, ChatGPTUnreachable

    if isinstance(exc, ChatGPTUnreachable):
        typer.echo("无法连接 OpenAI 登录服务；请检查 auth.openai.com 的云端网络权限。", err=True)
    elif isinstance(exc, ChatGPTAuthError):
        typer.echo("ChatGPT 登录不可用；请先运行 tradingagents login chatgpt 或注入官方登录文件。", err=True)
    else:
        typer.echo(f"无法查询订阅模型 ({type(exc).__name__})；请检查 OpenAI 网络访问。", err=True)


@app.command()
def login():
    """官方 ChatGPT 订阅 OAuth；先检查网络，再等待浏览器授权或终端回调。"""
    from tradingagents.llm_clients import chatgpt_auth
    from tradingagents.watchlist.auth import prepare_login_host

    try:
        chatgpt_auth._signing_keys()  # don't send the user into a flow whose exchange is blocked
        prepare_login_host()
        chatgpt_auth.sign_in(say=typer.echo)
    except Exception as exc:
        _auth_error(exc)
        raise typer.Exit(1) from None
    typer.echo("ChatGPT 订阅登录成功；请运行 ta-watchlist models 核对套餐型号。")


@app.command()
def probe(
    output: Annotated[Path, typer.Option(help="写入不含凭据的连通性和数据实测记录")] = Path("reports/validation"),
):
    """实测公开只读接口；分开记录网络、认证和实际数据，未通不记为成功。"""
    from tradingagents.watchlist.probe import run_probes

    report = run_probes(output)
    for row in report["network"]:
        typer.echo(f"{row['name']}: {row['status']}")
    for row in report["data"]:
        typer.echo(f"{row['name']}: {row['status']}")
    typer.echo(f"记录：{output / 'latest.json'}")
    if any(row["status"] == "network_blocked" for row in report["network"]):
        raise typer.Exit(1)
    if not report["public_data_passed"]:
        raise typer.Exit(2)


@app.command()
def models():
    """列出当前 ChatGPT 订阅允许的模型；不推测套餐权限。"""
    from tradingagents.llm_clients.chatgpt_auth import list_models
    from tradingagents.watchlist.auth import bootstrap_auth

    try:
        bootstrap_auth()
        for label, model in list_models():
            typer.echo(f"{model}\t{label}")
    except Exception as exc:
        _auth_error(exc)
        raise typer.Exit(1) from None


@app.command()
def run(
    date: Annotated[str | None, typer.Option(help="YYYY-MM-DD，默认上海当前日期")] = None,
    only: Annotated[str | None, typer.Option()] = None,
    skip_unchanged: Annotated[bool, typer.Option(help="同日期、标的和配置已有成功运行则跳过；不检测远端数据更新")] = False,
    watchlist: Annotated[Path, typer.Option()] = Path("watchlist.yaml"),
    config: Annotated[Path, typer.Option()] = Path("config/redteam.yaml"),
    reports: Annotated[Path, typer.Option()] = Path("reports"),
):
    """顺序运行完整代理图，输出完整报告、快照和索引。"""
    from tradingagents.llm_clients.chatgpt_auth import list_models
    from tradingagents.watchlist.auth import bootstrap_auth

    try:
        positions = load_positions(watchlist)
        cfg = load_config(config)
        # Skip-only/empty batches do not need an active subscription connection.
        def factory(**kwargs):
            effective = kwargs["config"]
            try:
                bootstrap_auth()
                available = {model for _, model in list_models()}
            except Exception as exc:
                _auth_error(exc)
                raise
            missing = [effective[key] for key in ("deep_think_llm", "quick_think_llm")
                       if effective[key] not in available]
            if missing:
                typer.echo("套餐不提供模型 " + ", ".join(missing) + "；运行 ta-watchlist models，更新配置并注释替换理由。", err=True)
                raise ValueError("套餐不提供已配置模型；运行 ta-watchlist models 并更新配置及替换理由注释")
            from tradingagents.graph.trading_graph import TradingAgentsGraph

            return TradingAgentsGraph(**kwargs)

        failures = run_batch(positions, cfg, reports, date, only, skip_unchanged, graph_factory=factory,
                             on_status=lambda msg: typer.echo(msg))
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    if failures:
        typer.echo("部分标的失败。先检查登录、套餐模型和网络；详情见 reports/last_batch.json。", err=True)
        raise typer.Exit(1)


@app.command()
def compare(ticker: str, reports: Annotated[Path, typer.Option()] = Path("reports")):
    """读取快照，对照最近运行；无需再次调用模型。"""
    try:
        typer.echo(compare_report(reports, ticker.upper()))
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None


if __name__ == "__main__":
    app()
