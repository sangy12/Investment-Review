import json
from unittest.mock import Mock

import pytest
import requests
from typer.testing import CliRunner

from tradingagents.llm_clients import chatgpt_auth
from tradingagents.watchlist import probe
from tradingagents.watchlist.auth import bootstrap_auth, prepare_login_host, read_login_callback
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


def test_login_callback_refuses_noninteractive_input(monkeypatch):
    import getpass
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    reader = Mock(side_effect=AssertionError("Must not fall back to echoed input"))
    monkeypatch.setattr(getpass, "getpass", reader)
    with pytest.raises(EOFError):
        read_login_callback()
    reader.assert_not_called()


def test_login_callback_refuses_getpass_echo_fallback(monkeypatch):
    import getpass
    import warnings

    from tradingagents.watchlist import auth as watch_auth

    def fallback(*args, **kwargs):
        warnings.warn("Could not hide input", getpass.GetPassWarning, stacklevel=2)
        return "must not be read"

    monkeypatch.setattr(getpass, "getpass", fallback)
    with pytest.raises(EOFError, match="cannot hide"):
        watch_auth._read_getpass_secret("prompt", None)


def test_auth_diagnostics_show_fixed_codes_without_exception_body(capsys):
    from tradingagents.watchlist.cli import _auth_error

    error = chatgpt_auth.ChatGPTAuthError("private callback or token must not be printed",
                                        code="token_request_refused", http_status=400,
                                        oauth_error="invalid_grant")
    _auth_error(error)
    output = capsys.readouterr().err
    assert "token_request_refused" in output and "400" in output and "invalid_grant" in output
    assert "private callback" not in output


def test_token_diagnostics_do_not_copy_arbitrary_remote_messages(monkeypatch):
    response = Mock(status_code=400)
    response.json.return_value = {"error": "untrusted server message containing private data"}
    monkeypatch.setattr(requests, "post", Mock(return_value=response))
    with pytest.raises(chatgpt_auth.ChatGPTAuthError) as captured:
        chatgpt_auth._token_request({}, "sign you in", "retry")
    assert captured.value.code == "token_request_refused"
    assert captured.value.http_status == 400
    assert captured.value.oauth_error is None


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


@pytest.mark.parametrize("csv,accepted", [
    ("Date,Close\n2026-11-06,186.64\n", True),
    ("Date,Close\n2026-11-06,\n", False),
    ("Date,Close\n2099-01-01,999\n", False),
    ("Date,Close\n2020-01-01,999\n", False),
])
def test_price_probe_uses_report_client_and_requires_in_window_prices(monkeypatch, csv, accepted):
    from tradingagents.dataflows import date_window
    from tradingagents.dataflows.vendors.yahoo import market
    from tradingagents.watchlist.probe_worker import check_data

    monkeypatch.setattr(date_window, "get_current_date", lambda: "2026-11-08")
    client = Mock(return_value="# Stock data\n" + csv)
    monkeypatch.setattr(market, "get_YFin_data_online", client)
    row = check_data("yahoo_nvda")
    assert row["data_accepted"] is accepted
    client.assert_called_once_with("NVDA", "2026-10-29", "2026-11-08")


@pytest.mark.parametrize("amount,accepted", [("100", True), ("", False)])
def test_statement_probe_requires_values_and_does_not_infer_hk_currency(monkeypatch, amount, accepted):
    from tradingagents.dataflows.vendors import akshare
    from tradingagents.watchlist.probe_worker import check_data

    monkeypatch.setattr(akshare, "get_income_statement", lambda _: "REPORT_DATE,AMOUNT\n2026-06-30," + amount + "\n")
    row = check_data("akshare_tencent")
    assert row["data_accepted"] is accepted
    assert row["currency_metadata"] == row["unit_metadata"] == {}


@pytest.mark.parametrize("stamp,url,accepted", [
    ("1700000000", "https://news.futunn.com/post/fixture", True),
    ("not-a-date", "https://news.futunn.com/post/fixture", False),
    ("9999999999999", "https://news.futunn.com/post/fixture", False),
    ("1700000000", "", False),
])
def test_futu_probe_requires_parseable_publication_time_and_link(monkeypatch, stamp, url, accepted):
    from tradingagents.watchlist.probe_worker import check_data

    response = Mock()
    response.json.return_value = {"code": 0, "data": [{"title": "Fixture", "publish_time": stamp, "url": url}]}
    get = Mock(return_value=response)
    monkeypatch.setattr(requests, "get", get)
    row = check_data("futu_tencent_notice")
    assert row["data_accepted"] is accepted
    assert get.call_args.kwargs["params"]["news_type"] == 2
