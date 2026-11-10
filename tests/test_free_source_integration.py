import io
import json
import zipfile
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.vendors import fred_public as fred
from tradingagents.watchlist import free_sources as free


def test_fred_zip_filters_series_numeric_and_dates_and_caches(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("README.txt", "metadata")
        z.writestr("monthly.csv", "observation_date,UNRATE\n2026-10-01,4.2\n")
        z.writestr("daily.csv", "observation_date,DGS10\n2025-01-01,3.0\n2026-11-08,.\n2026-11-09,4.1\n2026-11-11,9\n")
    rows = fred.parse_download(buf.getvalue(), "DGS10")
    fetch = Mock(return_value={"rows": rows, "retrieved_at": "2026-11-10T00:00:00Z"})
    monkeypatch.setattr(fred, "_download", fetch)
    monkeypatch.setattr(fred, "get_current_date", lambda: "2026-11-10")
    with run_config({"data_cache_dir": str(tmp_path)}):
        a = fred.get_macro_data("10y_treasury", "2026-11-10", 7)
        b = fred.get_macro_data("DGS10", "2026-11-10", 7)
    assert a == b
    assert "2026-11-09,4.1" in a and "2026-11-11" not in a and "2025-01-01" not in a
    assert "NOT publication dates" in a
    fetch.assert_called_once_with("DGS10")


def test_fred_history_unsupported_and_html_never_look_like_success(monkeypatch):
    monkeypatch.setattr(fred, "get_current_date", lambda: "2026-11-10")
    fetch = Mock(side_effect=AssertionError("No request"))
    monkeypatch.setattr(fred, "_download", fetch)
    for date, name in [("2020-01-01", "cpi"), ("2026-11-11", "cpi"), ("2026-11-10", "china_cpi")]:
        with pytest.raises(VendorUnavailableError):
            fred.get_macro_data(name, date)
    fetch.assert_not_called()
    with pytest.raises(ValueError):
        fred.parse_download(b"<html>not data</html>", "DGS10")


def test_community_filters_unrelated_future_undated_and_duplicates():
    position = {"ticker": "0700.HK", "name": "腾讯控股", "market": "HK"}
    now = datetime(2026, 11, 10, 2, tzinfo=UTC)
    text = "腾讯的经营表现值得关注，但是盈利预期仍然需要核实原始披露。"
    row = {"title": text, "publish_time": now.timestamp() * 1000,
           "url": "https://www.futunn.com/post/123?tracking=test"}
    rows = [row, row, {**row, "title": "其他公司的经营表现值得关注，但是预期需要核实。"},
            {**row, "publish_time": now.timestamp() + 86400}, {**row, "publish_time": None}]
    items = free.parse_community({"code": 0, "data": rows}, position, "2026-11-10", now=now)
    assert len(items) == 1
    assert items[0]["url"] == "https://www.futunn.com/post/123"
    assert items[0]["sentiment"] == "UNCLASSIFIED"
    assert items[0]["interactions"] == "UNKNOWN"


@pytest.mark.parametrize("failure", [False, True])
def test_free_snapshot_once_per_day_failure_cached_and_preview_no_fetch(tmp_path, monkeypatch, failure):
    cfg = {"data_cache_dir": str(tmp_path), "research_sources": {"consensus_snapshots": True}}
    position = {"ticker": "NVDA", "name": "NVIDIA", "market": "US"}
    monkeypatch.setattr(free, "today", lambda: "2026-11-10")
    fetch = Mock(side_effect=RuntimeError("sensitive") if failure else None,
                 return_value=[{"kind": "consensus_snapshot", "source": "fixture"}])
    monkeypatch.setattr(free, "forecast_items", fetch)
    assert free.prepare_free_evidence(position, "2026-11-10", cfg, cached_only=True)[0] == []
    fetch.assert_not_called()
    first = free.prepare_free_evidence(position, "2026-11-10", cfg)
    assert first == free.prepare_free_evidence(position, "2026-11-10", cfg)
    assert not free.prepare_free_evidence(position, "2020-01-01", cfg)[0]
    fetch.assert_called_once()
    assert "sensitive" not in json.dumps(first)


def test_us_shared_packet_gets_forecast_and_historical_never_calls(tmp_path, monkeypatch):
    from tradingagents.watchlist import evidence

    monkeypatch.setattr(evidence, "today", lambda: "2026-11-10")
    monkeypatch.setattr(free, "today", lambda: "2026-11-10")
    monkeypatch.setattr(free, "forecast_items", Mock(return_value=[{"kind": "consensus_snapshot"}]))
    cfg = {"data_cache_dir": str(tmp_path), "research_sources": {"enabled": True, "consensus_snapshots": True}}
    position = {"ticker": "NVDA", "name": "NVIDIA", "market": "US"}
    packet = evidence.prepare_evidence(position, "2026-11-10", cfg)
    assert packet["items"] == [{"kind": "consensus_snapshot"}]
    assert packet["mcp_calls"] == 0
    free.forecast_items.reset_mock()
    assert not evidence.prepare_evidence(position, "2020-01-01", cfg)["items"]
    free.forecast_items.assert_not_called()


def test_forecast_worker_rejects_metadata_only_empty_predictions(monkeypatch):
    import pandas as pd
    import yfinance as yf

    from tradingagents.dataflows.forecast_worker import tables

    stock = Mock()
    stock.get_earnings_estimate.return_value = pd.DataFrame({"avg": [None], "numberOfAnalysts": [20]}, index=["0y"])
    stock.get_revenue_estimate.return_value = pd.DataFrame({"avg": [100], "numberOfAnalysts": [2]}, index=["0y"])
    monkeypatch.setattr(yf, "Ticker", lambda ticker: stock)
    result = tables("NVDA", "US")
    assert len(result) == 1 and result[0]["title"] == "Revenue forecasts"
