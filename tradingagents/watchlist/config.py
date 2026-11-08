"""An opt-in profile; upstream defaults remain unchanged."""

from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from tradingagents.default_config import _apply_env_overrides, build_default_config


def today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def validate_date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("日期须为 YYYY-MM-DD")
    if value > today():
        raise ValueError("分析日期不能在未来")
    return value


def load_yaml(path):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: 须为 YAML mapping")
    return data


def load_positions(path):
    data = load_yaml(path)
    rows = data.get("positions")
    if not isinstance(rows, list):
        raise ValueError("positions 须为列表（允许空列表）")
    seen = set()
    result = []
    import re

    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("每个标的须为 mapping")
        ticker = row.get("ticker")
        if not isinstance(ticker, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.^=-]{0,30}", ticker):
            raise ValueError("ticker 非法或不安全")
        ticker = ticker.upper()
        expected = "A_SHARE" if ticker.endswith((".SS", ".SZ")) else "HK" if ticker.endswith(".HK") else "US"
        if row.get("market") != expected:
            raise ValueError(f"{ticker}: market 须为 {expected}")
        if expected == "A_SHARE" and not re.fullmatch(r"\d{6}\.(SS|SZ)", ticker):
            raise ValueError(f"{ticker}: A 股须为六位代码加 .SS/.SZ")
        if expected == "HK" and not re.fullmatch(r"\d{4,5}\.HK", ticker):
            raise ValueError(f"{ticker}: 港股须为四或五位代码加 .HK")
        identity = ticker.lstrip("0") if expected == "HK" else ticker
        if identity in seen:
            raise ValueError(f"重复标的: {ticker}")
        seen.add(identity)
        if any(not isinstance(row.get(k, ""), str) for k in ("name", "thesis")):
            raise ValueError("name/thesis 须为字符串")
        result.append({"ticker": ticker, "market": expected, "name": row.get("name", ticker), "thesis": row.get("thesis", "")})
    return result


def load_config(path):
    cfg = deepcopy(build_default_config())
    profile = load_yaml(path)
    for key, value in profile.items():
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(value)
        else:
            cfg[key] = value
    _apply_env_overrides(cfg)  # environment wins over the YAML profile
    for tier in ("deep", "quick"):
        if (cfg.get(f"{tier}_think_provider") or cfg["llm_provider"]) != "chatgpt":
            raise ValueError("红队 profile 的两层 provider 须为 chatgpt")
    if cfg["llm_provider"] != "chatgpt":
        raise ValueError("llm_provider 须为 chatgpt")
    for key in ("temperature", "max_tokens"):
        if cfg.get(key) is not None:
            raise ValueError(f"ChatGPT 订阅模式不接受 {key}，请移除配置/环境变量")
        cfg.pop(key, None)
    return cfg


def market_config(cfg, position):
    cfg = deepcopy(cfg)
    if position["market"] in ("A_SHARE", "HK"):
        # Explicit opt-in, pending comparison with the user's other data sources.
        china = cfg.pop("china_data_vendors", {})
        cfg["data_vendors"].update(china)
    else:
        cfg.pop("china_data_vendors", None)
    return cfg
