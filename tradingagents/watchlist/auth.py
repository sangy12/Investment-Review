"""Seed the official writable auth store once from an injected secret file."""

import json
import os
from pathlib import Path


def bootstrap_auth(source=None):
    source = source or os.environ.get("TRADINGAGENTS_CHATGPT_AUTH_SOURCE")
    raw = os.environ.get("TRADINGAGENTS_CHATGPT_AUTH_JSON")
    if not source and not raw:
        return
    from tradingagents.llm_clients import chatgpt_auth

    target = chatgpt_auth.AUTH_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    from tradingagents.dataflows.files import locked

    with locked(target):
        # A persistent refreshed token wins over the original seed on restarts.
        current = chatgpt_auth._read()
        if current.get("tokens"):
            return
        data = json.loads(Path(source).read_text(encoding="utf-8") if source else raw)
        if (not isinstance(data, dict) or not data.get("host_id")
                or not isinstance(data.get("account"), dict)
                or not data["account"].get("client_id")
                or not isinstance(data.get("tokens"), dict)
                or not data["tokens"].get("access_token")
                or not data["tokens"].get("refresh_token")):
            raise ValueError("注入文件须为官方 tradingagents login chatgpt 生成的完整登录文件")
        # Official VM import contract: retain a distinct stable ID for this VM,
        # not the ID copied from the machine which completed OAuth.
        data["host_id"] = chatgpt_auth._host_id(current)
        chatgpt_auth._write(data)  # official 0600 atomic writer


def prepare_login_host():
    """Persist this host's identity before the first OAuth attempt, even if it fails."""
    from tradingagents.dataflows.files import locked
    from tradingagents.llm_clients import chatgpt_auth

    target = chatgpt_auth.AUTH_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    with locked(target):
        data = chatgpt_auth._read()
        if not data.get("host_id"):
            data["host_id"] = chatgpt_auth._host_id(data)
            chatgpt_auth._write(data)
