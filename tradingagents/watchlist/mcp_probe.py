"""Discover official financial MCP tools without invoking any data or trading tool."""

import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import requests

_IFIND = "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-"
# iFinD URLs/header are from its official site's published configuration generator.
# The header value is used exactly as exported, with no guessed Bearer prefix.
PROVIDERS = {
    "ifind-stock": (_IFIND + "stock-mcp", "Authorization", "IFIND_MCP_AUTHORIZATION", False),
    "ifind-global": (_IFIND + "global-stock-mcp", "Authorization", "IFIND_MCP_AUTHORIZATION", False),
    "ifind-edb": (_IFIND + "edb-mcp", "Authorization", "IFIND_MCP_AUTHORIZATION", False),
    "ifind-news": (_IFIND + "news-mcp", "Authorization", "IFIND_MCP_AUTHORIZATION", False),
    "miaoxiang": ("https://mxapi.eastmoney.com/mxds/mcp", "em_api_key", "EM_API_KEY", True),
}


class ProbeFailure(Exception):
    def __init__(self, status, **metadata):
        self.status = status
        self.metadata = metadata


def _private_file(variable):
    directory = Path(os.environ.get("TRADINGAGENTS_MCP_AUTH_DIR", ".runtime/auth"))
    return directory / {"IFIND_MCP_AUTHORIZATION": "ifind-mcp.key", "EM_API_KEY": "miaoxiang.key"}[variable]


def save_credential(provider):
    """User-entered key stays in a private file, never shell arguments or output."""
    from tradingagents.watchlist.auth import read_private_terminal

    variables = {"ifind": "IFIND_MCP_AUTHORIZATION", "miaoxiang": "EM_API_KEY"}
    if provider not in variables:
        raise ValueError("Provider must be ifind or miaoxiang")
    value = read_private_terminal(f"{provider} 官方 MCP 密钥（输入隐藏）：").strip()
    if not value or "\r" in value or "\n" in value:
        raise ValueError("密钥须为非空单行文本；请复制官方配置的请求头值。")
    path = _private_file(variables[provider])
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temp = Path(handle.name)  # NamedTemporaryFile creates mode 0600
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return path


def _credential(variable):
    value = os.environ.get(variable, "").strip()
    source = os.environ.get(variable + "_FILE")
    if not value and not source and _private_file(variable).is_file():
        source = _private_file(variable)
    if not value and source:
        path = Path(source)
        if path.stat().st_mode & 0o077:
            raise ProbeFailure("credential_file_permissions")
        value = path.read_text(encoding="utf-8").strip()
    if "\r" in value or "\n" in value:
        raise ProbeFailure("invalid_credential_format")
    return value


def _message(response, request_id, timeout=30):
    """Read bounded JSON or a matching SSE event; never retain the raw response."""
    total, lines = 0, []
    deadline = time.monotonic() + timeout
    sse = "text/event-stream" in response.headers.get("Content-Type", "")
    for line in response.iter_lines(chunk_size=1 if sse else 1024):
        total += len(line)
        if total > 1024 * 1024 or time.monotonic() > deadline:
            raise ProbeFailure("response_limit")
        if sse:
            if line.startswith(b"data:"):
                lines.append(line[5:].lstrip())
            elif line:
                continue
        else:
            lines.append(line)
        if not lines or (sse and line):
            continue
        try:
            body = json.loads(b"\n".join(lines))
        except ValueError:
            if sse:
                lines = []
            continue
        if isinstance(body, dict) and body.get("id") == request_id:
            return body
        lines = []
    raise ProbeFailure("invalid_response")


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secrets): _redact(item, secrets) for key, item in value.items()}
    return value


def _rpc(session, url, headers, payload, timeout=15):
    with session.post(url, headers=headers, json=payload, timeout=(10, timeout),
                      stream=True, allow_redirects=False) as response:
        status = response.status_code
        if status >= 300:
            label = "authentication_or_permission_required" if status in (401, 403) else "http_error"
            raise ProbeFailure(label, http_status=status)
        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            headers["Mcp-Session-Id"] = session_id  # kept only in memory, never in reports
        if "id" not in payload:
            return {}
        body = _message(response, payload["id"], timeout=max(30, timeout))
    if "error" in body:
        error = body["error"]
        code = error.get("code") if isinstance(error, dict) else None
        raise ProbeFailure("rpc_error", rpc_code=code if isinstance(code, int) else None)
    if not isinstance(body.get("result"), dict):
        raise ProbeFailure("invalid_response")
    return body["result"]


def inspect_provider(name):
    url, header, variable, initialize = PROVIDERS[name]
    row = {"provider": name, "url": url, "credential_variable": variable,
           "data_accepted": False, "tools_called": 0, "quota_verified": False}
    try:
        secret = _credential(variable)
        row["credential_present"] = bool(secret)
        if not secret:
            return {**row, "status": "missing_credential"}
        headers = {header: secret, "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        tools, cursor = [], None
        with requests.Session() as session:
            if initialize:
                result = _rpc(session, url, headers, {"jsonrpc": "2.0", "id": "init", "method": "initialize",
                              "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                         "clientInfo": {"name": "investment-review-inventory", "version": "1"}}})
                headers["MCP-Protocol-Version"] = result.get("protocolVersion", "2025-03-26")
                _rpc(session, url, headers, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            for page in range(5):
                result = _rpc(session, url, headers, {"jsonrpc": "2.0", "id": page + 1,
                              "method": "tools/list", "params": {"cursor": cursor} if cursor else {}})
                batch = result.get("tools")
                if not isinstance(batch, list) or not all(isinstance(t, dict) and isinstance(t.get("name"), str)
                                                         and isinstance(t.get("inputSchema"), dict) for t in batch):
                    raise ProbeFailure("invalid_tool_inventory")
                tools.extend({key: tool[key] for key in ("name", "description", "inputSchema", "annotations")
                              if key in tool} for tool in batch)
                cursor = result.get("nextCursor")
                if not cursor:
                    break
            if cursor:
                raise ProbeFailure("inventory_pagination_limit")
        # Even an upstream echo of the submitted credential must not enter a report.
        secrets = [secret]
        if secret.lower().startswith("bearer ") and secret[7:].strip():
            secrets.append(secret[7:].strip())
        tools = _redact(tools, secrets)
        return {**row, "status": "inventory_available" if tools else "empty_inventory",
                "tool_count": len(tools), "tools": tools}
    except ProbeFailure as exc:
        return {**row, "status": exc.status, **exc.metadata}
    except requests.exceptions.ProxyError:
        return {**row, "status": "proxy_error"}
    except requests.exceptions.Timeout:
        return {**row, "status": "timeout"}
    except requests.RequestException:
        return {**row, "status": "network_error"}
    except (OSError, ValueError):
        return {**row, "status": "local_configuration_or_response_error"}


def run_inventory(provider, output):
    from tradingagents.watchlist.runner import atomic_text

    names = list(PROVIDERS) if provider == "all" else [provider]
    if any(name not in PROVIDERS for name in names):
        raise ValueError("Provider must be all or one of: " + ", ".join(PROVIDERS))
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(inspect_provider, names))
    report = {"generated_at": datetime.now(UTC).isoformat(), "providers": rows,
              "note": "Discovery only; no tools/call, no quota/free-entitlement claim, no tools exposed to agents."}
    atomic_text(Path(output) / "mcp-latest.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report
