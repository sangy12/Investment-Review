import json
from unittest.mock import Mock

import pytest

from tradingagents.watchlist import mcp_probe as probe


class Response:
    def __init__(self, body=None, status=200, headers=None, lines=None):
        self.status_code = status
        self.headers = headers or {"Content-Type": "application/json"}
        self.lines = lines if lines is not None else [json.dumps(body).encode()]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_lines(self, **kwargs):
        yield from self.lines


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def post(self, url, **kwargs):
        self.calls.append((url, {**kwargs, "headers": dict(kwargs["headers"])}))
        return next(self.responses)


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADINGAGENTS_MCP_AUTH_DIR", str(tmp_path / "private"))
    for variable in ("EM_API_KEY", "IFIND_MCP_AUTHORIZATION"):
        monkeypatch.delenv(variable, raising=False)
        monkeypatch.delenv(variable + "_FILE", raising=False)


def test_missing_key_is_not_a_data_failure_or_network_request(monkeypatch, tmp_path):
    session = Mock(side_effect=AssertionError("No key must not launch authenticated requests"))
    monkeypatch.setattr(probe.requests, "Session", session)
    report = probe.run_inventory("all", tmp_path)
    assert all(row["status"] == "missing_credential" and not row["data_accepted"] for row in report["providers"])
    session.assert_not_called()


def test_miaoxiang_discovery_never_invokes_tools_or_records_secrets(monkeypatch):
    secret = 'fixture-"secret'
    monkeypatch.setenv("EM_API_KEY", secret)
    session = Session([
        Response({"id": "init", "result": {"protocolVersion": "2025-03-26"}},
                 headers={"Content-Type": "application/json", "Mcp-Session-Id": "private-session"}),
        Response(status=202),
        Response({"id": 1, "result": {"tools": [{"name": "query", "inputSchema": {"type": "object"},
                                                        "description": "Echo " + secret}]}}),
    ])
    monkeypatch.setattr(probe.requests, "Session", lambda: session)
    row = probe.inspect_provider("miaoxiang")
    assert row["status"] == "inventory_available"
    assert row["tools_called"] == 0 and not row["data_accepted"] and not row["quota_verified"]
    output = json.dumps(row)
    assert secret not in str(row) and "private-session" not in output
    assert "[REDACTED]" in output
    methods = [kwargs["json"]["method"] for _, kwargs in session.calls]
    assert methods == ["initialize", "notifications/initialized", "tools/list"]
    assert all(not kwargs["allow_redirects"] for _, kwargs in session.calls)
    assert session.calls[-1][1]["headers"]["Mcp-Session-Id"] == "private-session"


@pytest.mark.parametrize("status,label", [(401, "authentication_or_permission_required"),
                                         (403, "authentication_or_permission_required"), (302, "http_error")])
def test_http_failure_does_not_follow_redirect_or_copy_error_body(monkeypatch, status, label):
    monkeypatch.setenv("IFIND_MCP_AUTHORIZATION", "raw-exported-token")
    session = Session([Response({"secret": "must-not-be-read"}, status=status)])
    monkeypatch.setattr(probe.requests, "Session", lambda: session)
    row = probe.inspect_provider("ifind-global")
    assert row["status"] == label and row["http_status"] == status
    assert "must-not-be-read" not in str(row)
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == probe.PROVIDERS["ifind-global"][0]
    assert kwargs["headers"]["Authorization"] == "raw-exported-token"
    assert kwargs["json"]["method"] == "tools/list"


def test_sse_inventory_ignores_notifications_and_reads_matching_id():
    result = {"id": 1, "result": {"tools": []}}
    response = Response(headers={"Content-Type": "text/event-stream"}, lines=[
        b": heartbeat", b"", b'data: {"method":"notifications/notice"}', b"",
        b"event: message", b"data: " + json.dumps(result).encode(), b"",
    ])
    assert probe._message(response, 1) == result


def test_inventory_pagination_is_bounded_and_not_a_silent_partial_pass(monkeypatch):
    monkeypatch.setenv("IFIND_MCP_AUTHORIZATION", "fixture-token")
    session = Session([Response({"id": page + 1, "result": {"tools": [], "nextCursor": "next"}})
                       for page in range(5)])
    monkeypatch.setattr(probe.requests, "Session", lambda: session)
    row = probe.inspect_provider("ifind-stock")
    assert row["status"] == "inventory_pagination_limit" and not row["data_accepted"]
    assert len(session.calls) == 5


def test_world_readable_credential_file_is_refused_without_printing_it(monkeypatch, tmp_path):
    path = tmp_path / "key"
    path.write_text("fixture-private-token")
    path.chmod(0o644)
    monkeypatch.setenv("EM_API_KEY_FILE", str(path))
    row = probe.inspect_provider("miaoxiang")
    assert row["status"] == "credential_file_permissions"
    assert "fixture-private-token" not in str(row)


def test_hidden_key_setup_is_private_and_used_without_environment_value(monkeypatch, capsys):
    from tradingagents.watchlist import auth

    monkeypatch.setattr(auth, "read_private_terminal", lambda _: "fixture-private-token")
    path = probe.save_credential("ifind")
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert probe._credential("IFIND_MCP_AUTHORIZATION") == "fixture-private-token"
    assert "fixture-private-token" not in capsys.readouterr().out


def test_key_setup_rejects_multiline_configuration_without_saving(monkeypatch):
    from tradingagents.watchlist import auth

    monkeypatch.setattr(auth, "read_private_terminal", lambda _: "not-a-key\nsecond-line")
    with pytest.raises(ValueError, match="单行"):
        probe.save_credential("miaoxiang")
    assert not probe._private_file("EM_API_KEY").exists()
