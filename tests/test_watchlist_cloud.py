import json
from unittest.mock import Mock

import requests
from typer.testing import CliRunner

from tradingagents.llm_clients import chatgpt_auth
from tradingagents.watchlist import probe
from tradingagents.watchlist.auth import bootstrap_auth, prepare_login_host
from tradingagents.watchlist.cli import app


def test_vm_import_preserves_distinct_stable_host(tmp_path, monkeypatch):
    target = tmp_path / "vm/chatgpt-auth.json"
    monkeypatch.setattr(chatgpt_auth, "AUTH_FILE", target)
    prepare_login_host()
    vm_host = chatgpt_auth._read()["host_id"]
    seed = {"host_id": "laptop-host", "account": {"client_id": "oaiapp_fixture"},
            "tokens": {"access_token": "fixture-access", "refresh_token": "fixture-refresh"}}
    monkeypatch.setenv("TRADINGAGENTS_CHATGPT_AUTH_JSON", json.dumps(seed))
    bootstrap_auth()
    assert chatgpt_auth._read()["host_id"] == vm_host != "laptop-host"
    assert target.stat().st_mode & 0o777 == 0o600
    # A repeated initialization must not replace the existing cloud identity.
    prepare_login_host()
    assert chatgpt_auth._read()["host_id"] == vm_host


def test_login_checks_network_before_consent(monkeypatch):
    monkeypatch.setattr(chatgpt_auth, "_signing_keys", Mock(side_effect=chatgpt_auth.ChatGPTUnreachable("blocked")))
    sign_in = Mock()
    monkeypatch.setattr(chatgpt_auth, "sign_in", sign_in)
    result = CliRunner().invoke(app, ["login"])
    assert result.exit_code == 1
    assert "auth.openai.com" in result.output
    sign_in.assert_not_called()


def test_proxy_policy_denial_is_not_auth_or_empty_data(monkeypatch):
    monkeypatch.setattr(probe.requests, "get", Mock(side_effect=requests.exceptions.ProxyError("Tunnel connection failed: 403 Forbidden")))
    row = probe.check_network(("test", "https://example.com"))
    assert row["status"] == "network_blocked"
    assert not row["data_accepted"]
    monkeypatch.setattr(probe.requests, "get", Mock(return_value=Mock(status_code=401)))
    assert probe.check_network(("test", "https://example.com"))["status"] == "authentication_required"


def test_blocked_probe_never_claims_live_data_or_calls_vendor(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "check_network", lambda target: {"name": target[0], "status": "network_blocked", "data_accepted": False})
    worker = Mock(side_effect=AssertionError("Blocked origin must not launch a data worker"))
    monkeypatch.setattr(probe, "_data_job", worker)
    result = probe.run_probes(tmp_path)
    worker.assert_not_called()
    assert all(not row["data_accepted"] for row in result["data"])
    assert json.loads((tmp_path / "latest.json").read_text())["network"]
