"""Optional China/HK read-only vendor. No order/execution endpoints.

AKShare wraps upstream websites, rather than providing a stable data service.
Conservatively withhold historical fundamentals and revised macro series: a
period-end or even an announcement date is not an as-filed vintage guarantee.
"""

import importlib
import re
from datetime import timedelta

import pandas as pd

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.date_window import get_current_date, is_historical
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorUnavailableError,
)


def _symbol(ticker):
    ticker = ticker.upper()
    match = re.fullmatch(r"(\d{6})\.(SS|SZ)", ticker)
    if match:
        return "A_SHARE", match[1], ("SH" if match[2] == "SS" else "SZ") + match[1]
    match = re.fullmatch(r"(\d{4,5})\.HK", ticker)
    if match:
        return "HK", match[1].zfill(5), match[1].zfill(5)
    raise NoMarketDataError(ticker, detail="AKShare adapter only supports .SS/.SZ/.HK")


def _call(name, **kwargs):
    try:
        ak = importlib.import_module("akshare")
    except ImportError:
        raise VendorNotConfiguredError("Install tradingagents[china] to use AKShare") from None
    try:
        return getattr(ak, name)(**kwargs)
    except Exception as exc:
        # Do not echo URLs/cookies from upstream exceptions.
        raise VendorUnavailableError(f"AKShare {name} failed ({type(exc).__name__})") from None


def _date(value):
    value = value or get_current_date()
    parsed = pd.Timestamp(value).strftime("%Y-%m-%d")
    if parsed != value or parsed > get_current_date():
        raise ValueError("Date must be YYYY-MM-DD and no later than today")
    return parsed


def _withheld(date, subject):
    if is_historical(date):
        return (f"DATA_UNAVAILABLE: {subject} 数据不可用 as of {date}. "
                "AKShare current endpoints do not supply verified as-filed historical vintages; "
                "current/restated values must not be backfilled. This is not evidence of no risk.")
    return None


def _csv(frame, label):
    if frame is None or frame.empty:
        raise NoMarketDataError(label, detail="AKShare returned no usable rows")
    return f"# Source: AKShare / East Money; {label}\n" + frame.to_csv(index=False)


def stock_frame(ticker, start_date, end_date):
    market, code, _ = _symbol(ticker)
    start, end = _date(start_date), _date(end_date)
    if start > end or end > get_current_date():
        raise ValueError("Invalid/future price window")
    frame = _call("stock_zh_a_hist" if market == "A_SHARE" else "stock_hk_hist",
                  symbol=code, period="daily", start_date=start.replace("-", ""),
                  end_date=end.replace("-", ""), adjust="")  # no future-adjusted prices
    if frame is None or frame.empty:
        raise NoMarketDataError(ticker, detail="no AKShare prices")
    frame = frame.rename(columns={"日期": "Date", "开盘": "Open", "最高": "High", "最低": "Low",
                                  "收盘": "Close", "成交量": "Volume"})
    required = ("Date", "Open", "High", "Low", "Close", "Volume")
    if not all(col in frame for col in required):
        raise VendorUnavailableError("AKShare OHLCV schema changed")
    frame = frame[list(required)].copy()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.dropna(subset=["Date"])
    frame = frame[(frame["Date"] >= start) & (frame["Date"] <= end)].sort_values("Date")
    for column in required[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=list(required[1:]))
    if frame.empty:
        raise NoMarketDataError(ticker, detail="no valid AKShare OHLCV in requested window")
    # East Money A-share and HK history use lots (手); normalize to shares.
    # HK board lots vary by instrument, so do not infer a share count for HK.
    if market == "A_SHARE":
        frame["Volume"] *= 100
    return frame


def get_stock_data(symbol, start_date, end_date):
    market, _, _ = _symbol(symbol)
    unit = "shares" if market == "A_SHARE" else "upstream units (HK board lot/share semantics unverified)"
    return _csv(stock_frame(symbol, start_date, end_date),
                f"{symbol} {start_date}..{end_date}; unadjusted prices; volume={unit}")


def _statement(ticker, freq, as_of_date, kind):
    market, code, vendor_symbol = _symbol(ticker)
    date = _date(as_of_date)
    withheld = _withheld(date, f"{ticker} {kind}")
    if withheld:
        return withheld  # before importing AKShare or issuing any request
    if freq not in ("annual", "quarterly"):
        raise ValueError("freq must be annual or quarterly")
    names = {"balance": ("stock_balance_sheet_by_report_em", "资产负债表"),
             "income": ("stock_profit_sheet_by_report_em", "利润表"),
             "cashflow": ("stock_cash_flow_sheet_by_report_em", "现金流量表")}
    method, chinese = names[kind]
    if market == "HK":
        frame = _call("stock_financial_hk_report_em", stock=code, symbol=chinese,
                      indicator="年度" if freq == "annual" else "报告期")
    else:
        frame = _call(method, symbol=vendor_symbol)
    if frame is None or frame.empty or "REPORT_DATE" not in frame:
        raise NoMarketDataError(ticker, detail="missing AKShare financial statements/report dates")
    frame = frame.copy()
    periods = pd.to_datetime(frame["REPORT_DATE"], errors="coerce")
    frame = frame[periods.notna() & (periods <= date)]
    if freq == "annual" and market == "A_SHARE":
        periods = pd.to_datetime(frame["REPORT_DATE"])
        frame = frame[(periods.dt.month == 12) & (periods.dt.day == 31)]
    if "NOTICE_DATE" in frame:
        disclosed = pd.to_datetime(frame["NOTICE_DATE"], errors="coerce")
        frame = frame[disclosed.isna() | (disclosed < pd.Timestamp(date) + timedelta(days=1))]
    # Keep all line items for the latest four reporting periods, especially HK long tables.
    dates = sorted(frame["REPORT_DATE"].dropna().astype(str).unique(), reverse=True)[:4]
    frame = frame[frame["REPORT_DATE"].astype(str).isin(dates)]
    return _csv(frame, f"{ticker} {chinese}; current snapshot {date}; {freq}; "
                "frequency selects reporting dates, NOT standalone quarters. Balance sheets are point-in-time; "
                "income/cashflow periods may be year-to-date (HK may be interim). "
                "Vendor line-item labels require issuer reconciliation: HK 营业额 and 营运收入 may differ. "
                "use explicit upstream currency/unit fields only; if absent they are UNKNOWN, "
                "do not assume quote currency or combine amounts with other sources")


def get_balance_sheet(ticker, freq="quarterly", as_of_date=None):
    return _statement(ticker, freq, as_of_date, "balance")


def get_income_statement(ticker, freq="quarterly", as_of_date=None):
    return _statement(ticker, freq, as_of_date, "income")


def get_cashflow(ticker, freq="quarterly", as_of_date=None):
    return _statement(ticker, freq, as_of_date, "cashflow")


def get_fundamentals(ticker, as_of_date=None):
    market, code, _ = _symbol(ticker)
    date = _date(as_of_date)
    withheld = _withheld(date, f"{ticker} profile")
    if withheld:
        return withheld
    frame = _call("stock_individual_info_em", symbol=code) if market == "A_SHARE" else _call("stock_hk_company_profile_em", symbol=code)
    return _csv(frame, f"{ticker} overview; current snapshot {date}; valuation/statement tools provide separate evidence")


def _news_window(frame, start, end, label, limit):
    if frame is None or frame.empty or "发布时间" not in frame:
        raise NoMarketDataError(label, detail="news timestamps unavailable")
    frame = frame.copy()
    dates = pd.to_datetime(frame["发布时间"], errors="coerce")
    end_exclusive = pd.Timestamp(end) + timedelta(days=1)
    frame = frame[dates.notna() & (dates >= pd.Timestamp(start)) & (dates < end_exclusive)]
    if frame.empty:
        return f"DATA_UNAVAILABLE: {label} recent feed has no verified coverage for {start}..{end}; not evidence of no news."
    return ("# Coverage: partial recent feed, not an exhaustive archive; publication times Asia/Shanghai\n"
            + _csv(frame.tail(limit), label))


def get_news(ticker, start_date, end_date):
    market, code, _ = _symbol(ticker)
    if market == "HK":
        # Numeric HK codes in this A-share endpoint can match unrelated companies.
        raise NoMarketDataError(ticker, detail="East Money stock_news_em is not verified for HK; use configured Yahoo fallback")
    if is_historical(end_date):
        return f"DATA_UNAVAILABLE: {ticker} historical domestic news coverage is not archived by this adapter."
    return _news_window(_call("stock_news_em", symbol=code), start_date, end_date, ticker,
                        get_config().get("news_article_limit", 20))


def get_global_news(as_of_date, look_back_days=7, limit=10):
    date = _date(as_of_date)
    if is_historical(date):
        return "DATA_UNAVAILABLE: domestic live news has no historical archive."
    config = get_config()
    look_back_days = look_back_days if look_back_days is not None else config.get("global_news_lookback_days", 7)
    limit = limit if limit is not None else config.get("global_news_article_limit", 10)
    start = (pd.Timestamp(date) - timedelta(days=look_back_days)).strftime("%Y-%m-%d")
    return _news_window(_call("stock_info_global_em"), start, date, "domestic macro news", limit)


def get_macro_data(indicator, as_of_date, look_back_days=365):
    date = _date(as_of_date)
    withheld = _withheld(date, "China revised macro series")
    if withheld:
        return withheld
    look_back_days = look_back_days if look_back_days is not None else 365
    methods = {"china_cpi": "macro_china_cpi", "cpi": "macro_china_cpi",
               "china_gdp": "macro_china_gdp", "gdp": "macro_china_gdp",
               "china_lpr": "macro_china_lpr"}
    if indicator not in methods:
        return "DATA_UNAVAILABLE: supported China indicators: china_cpi, china_gdp, china_lpr. US indicators are not substituted."
    frame = _call(methods[indicator])
    if frame is None or frame.empty:
        raise NoMarketDataError(indicator, detail="no China macro rows")
    if indicator == "china_lpr" and "TRADE_DATE" in frame:
        timestamps = pd.to_datetime(frame["TRADE_DATE"], errors="coerce")
        frame = frame[(timestamps <= date) & (timestamps >= pd.Timestamp(date) - timedelta(days=look_back_days))]
        frame = frame.sort_values("TRADE_DATE").tail(12)
    else:
        period_column = "月份" if indicator in ("china_cpi", "cpi") else "季度"
        if period_column not in frame:
            raise VendorUnavailableError("AKShare macro period schema changed")
        # These current East Money series label periods in fixed-width Chinese dates.
        frame = frame.sort_values(period_column, ascending=False).head(12)
    return _csv(frame, f"China {indicator}; latest revised snapshot {date}; "
                "period is not publication date; no historical vintage; macro window may be broader than requested")
