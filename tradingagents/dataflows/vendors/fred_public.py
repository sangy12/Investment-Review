"""Keyless FRED downloads for current revised snapshots, never historical vintages."""

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.date_window import get_current_date
from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError
from tradingagents.dataflows.files import locked, replace_file

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SERIES = {
    "CPIAUCSL": ("CPI", "index 1982-1984=100, seasonally adjusted", "monthly"),
    "CPILFESL": ("Core CPI", "index 1982-1984=100, seasonally adjusted", "monthly"),
    "UNRATE": ("Unemployment rate", "percent, seasonally adjusted", "monthly"),
    "DGS10": ("10-year Treasury yield", "percent, not seasonally adjusted", "daily"),
    "DGS2": ("2-year Treasury yield", "percent, not seasonally adjusted", "daily"),
    "FEDFUNDS": ("Effective federal funds rate", "percent, not seasonally adjusted", "monthly"),
    "PCEPILFE": ("Core PCE price index", "index 2017=100, seasonally adjusted", "monthly"),
    "PCEPI": ("PCE price index", "index 2017=100, seasonally adjusted", "monthly"),
}


def parse_download(content, series):
    if len(content) > 4 * 1024 * 1024:
        raise ValueError("download_size_limit")
    files = [content]
    if zipfile.is_zipfile(io.BytesIO(content)):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > 20 or sum(m.file_size for m in members) > 8 * 1024 * 1024:
                raise ValueError("archive_size_limit")
            files = [archive.read(m) for m in members if m.filename.lower().endswith(".csv")]
    for data in files:
        frame = pd.read_csv(io.BytesIO(data))
        if "observation_date" not in frame or series not in frame:
            continue
        frame = frame[["observation_date", series]].copy()
        frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
        frame[series] = pd.to_numeric(frame[series], errors="coerce")
        frame = frame.dropna().sort_values("observation_date").drop_duplicates("observation_date", keep="last")
        frame["observation_date"] = frame["observation_date"].dt.strftime("%Y-%m-%d")
        return frame.to_dict("records")
    raise ValueError("series_not_in_download")


def _download(series):
    with requests.get(URL, params={"id": series}, timeout=20, stream=True, allow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError("download_http_error")
        content = bytearray()
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content) > 4 * 1024 * 1024:
                raise ValueError("download_size_limit")
    return {"retrieved_at": datetime.now(UTC).isoformat(), "rows": parse_download(bytes(content), series)}


def get_macro_data(indicator, as_of_date, look_back_days=None):
    from tradingagents.dataflows.vendors.fred import MACRO_SERIES

    date = pd.Timestamp(as_of_date).strftime("%Y-%m-%d")
    if date != as_of_date or date != get_current_date():
        raise VendorUnavailableError("FRED public CSV has no verified historical vintage; use authenticated FRED for as-filed history")
    series = MACRO_SERIES.get(indicator.strip().lower(), indicator.strip().upper())
    if series not in SERIES:
        raise VendorUnavailableError("FRED public series not validated; use configured FRED API")
    days = 365 if look_back_days is None else int(look_back_days)
    if not 1 <= days <= 3650:
        raise ValueError("look_back_days must be 1..3650")
    directory = Path(get_config()["data_cache_dir"]) / "fred_public"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{series}-{date}.json"
    try:
        with locked(path):
            if path.exists():
                record = json.loads(path.read_text())
            else:
                record = _download(series)
                replace_file(path, lambda temp: Path(temp).write_text(json.dumps(record)))
        start = (pd.Timestamp(date) - timedelta(days=days)).strftime("%Y-%m-%d")
        frame = pd.DataFrame(record["rows"])
        frame = frame[(frame.observation_date >= start) & (frame.observation_date <= date)].tail(40)
        if frame.empty:
            raise NoMarketDataError(series, detail="no observations within requested window")
        title, unit, frequency = SERIES[series]
        return (f"# {title} ({series})\nSource: FRED public download {URL}\n"
                f"Retrieved at: {record['retrieved_at']}\nUnits: {unit}; frequency: {frequency}\n"
                "Current revised snapshot only. Observation dates are NOT publication dates; "
                "release dates and historical vintages are UNKNOWN. Do not calculate inflation rates from index levels without comparable periods.\n"
                + frame.to_csv(index=False))
    except NoMarketDataError:
        raise
    except Exception as exc:
        raise VendorUnavailableError(f"FRED public download unavailable ({type(exc).__name__})") from None
