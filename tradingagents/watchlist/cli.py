import json
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
    diagnostics = {
        "signing_keys_unreachable": "无法取得登录签名公钥。",
        "token_network_error": "令牌交换网络请求失败。",
        "token_service_unavailable": "令牌服务暂不可用或被限流。",
        "token_request_refused": "令牌端点拒绝本次请求。",
        "token_response_invalid": "令牌响应格式不可用。",
        "login_timeout": "等待回调超时；重新运行 login，并使用本次新链接。",
        "consent_not_completed": "浏览器授权未完成。",
        "client_registration_failed": "未完成应用注册。",
        "id_token_signature_invalid": "登录令牌签名验证失败。",
        "id_token_nonce_mismatch": "令牌与本次登录不匹配；请勿复用旧回调。",
        "id_token_claims_invalid": "令牌的签发者、受众、有效期或身份声明不匹配。",
        "account_mismatch": "与本实例已登记账户不一致。",
        "plan_scope_missing": "未获得 ChatGPT 订阅使用权限。",
    }
    code = getattr(exc, "code", None)
    if code in diagnostics:
        typer.echo(f"诊断：{code} — {diagnostics[code]}", err=True)
    status = getattr(exc, "http_status", None)
    if isinstance(status, int) and 100 <= status <= 599:
        typer.echo(f"HTTP 状态：{status}", err=True)
    oauth_error = getattr(exc, "oauth_error", None)
    if oauth_error in {"invalid_grant", "invalid_client", "invalid_request", "access_denied", "invalid_scope",
                       "unauthorized_client", "unsupported_grant_type", "server_error", "temporarily_unavailable",
                       "invalid_resource"}:
        typer.echo(f"OAuth 错误：{oauth_error}", err=True)


@app.command()
def login():
    """官方 ChatGPT 订阅 OAuth；先检查网络，再等待浏览器授权或终端回调。"""
    from tradingagents.llm_clients import chatgpt_auth
    from tradingagents.watchlist.auth import prepare_login_host, read_login_callback

    try:
        chatgpt_auth._signing_keys()  # don't send the user into a flow whose exchange is blocked
        prepare_login_host()
        typer.echo("远程云端登录：请在浏览器打开下方官方链接，由本人完成授权。")
        typer.echo("若最后跳转到 127.0.0.1 显示拒绝连接，把地址栏完整回调地址粘回本终端并按回车；输入隐藏。")
        typer.echo("请勿把回调地址发到聊天或保存到 Git。登录等待十分钟，超时后需重新生成链接。")
        chatgpt_auth.sign_in(say=typer.echo, read_line=read_login_callback)
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
def sources(
    only: Annotated[str, typer.Option(help="标的代码")],
    cached_only: Annotated[bool, typer.Option(help="默认仅预览缓存，不触发付费查询")] = True,
    refresh: Annotated[bool, typer.Option(help="显式重查同报告期（可能消耗积分），须同时 --no-cached-only")] = False,
    watchlist: Annotated[Path, typer.Option()] = Path("watchlist.yaml"),
    config: Annotated[Path, typer.Option()] = Path("config/redteam.yaml"),
    output: Annotated[Path, typer.Option()] = Path("reports/sources"),
):
    """预览供各代理共用的来源材料，允许脱离模型检查接入结果。"""
    from tradingagents.watchlist.config import market_config, today
    from tradingagents.watchlist.evidence import prepare_evidence, render_evidence
    from tradingagents.watchlist.runner import atomic_text

    try:
        position = next((p for p in load_positions(watchlist) if p["ticker"] == only.upper()), None)
        if position is None:
            raise ValueError("清单中没有这个标的")
        if cached_only and refresh:
            raise ValueError("--refresh 须同时指定 --no-cached-only")
        cfg = market_config(load_config(config), position)
        packet = prepare_evidence(position, today(), cfg, cached_only=cached_only, refresh=refresh)
        atomic_text(output / (position["ticker"] + ".json"), json.dumps(packet, ensure_ascii=False, indent=2))
        atomic_text(output / (position["ticker"] + ".md"), render_evidence(packet))
        typer.echo(f"{position['ticker']}: 材料 {len(packet['items'])} 项，缺口 {len(packet['gaps'])} 项，付费调用 {packet['mcp_calls']} 次。")
    except (ValueError, OSError) as exc:
        typer.echo(f"来源准备失败：{type(exc).__name__}", err=True)
        raise typer.Exit(2) from None


@app.command()
def mcp_key(provider: Annotated[str, typer.Option(help="ifind / miaoxiang")]):
    """在可信终端隐藏录入 MCP 密钥；仅保存到私有运行目录。"""
    from tradingagents.watchlist.mcp_probe import save_credential

    try:
        save_credential(provider)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    except (EOFError, OSError):
        typer.echo("无法安全录入或保存；请在云端交互终端运行，或通过安全环境变量/secret file 注入。", err=True)
        raise typer.Exit(2) from None
    typer.echo("密钥已保存到私有运行目录（0600），未显示密钥。请运行 mcp-probe 验证工具清单。")


@app.command()
def mcp_probe(
    provider: Annotated[str, typer.Option(help="all / ifind-stock / ifind-global / ifind-edb / ifind-news / miaoxiang")] = "all",
    output: Annotated[Path, typer.Option()] = Path("reports/validation"),
):
    """只列出官方金融 MCP 工具；不调用数据、账户或交易工具。"""
    from tradingagents.watchlist.mcp_probe import run_inventory

    try:
        report = run_inventory(provider, output)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    for row in report["providers"]:
        typer.echo(f"{row['provider']}: {row['status']} (tools={row.get('tool_count', 0)})")
    typer.echo(f"记录：{output / 'mcp-latest.json'}；工具清单不代表数据、额度或费用验收通过。")
    if any(row["status"] != "inventory_available" for row in report["providers"]):
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
    resume_only: Annotated[bool, typer.Option(help="仅恢复匹配断点，补充材料仅读缓存；不匹配时不调用模型")] = False,
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
                             on_status=lambda msg: typer.echo(msg), resume_only=resume_only)
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    if failures:
        if any(row.get("error_code") == "subscription_usage_limit" for row in failures):
            typer.echo("ChatGPT 订阅共享额度已达上限；已停止批次并保留断点。额度重置后加 --resume-only 继续。", err=True)
            raise typer.Exit(1)
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
