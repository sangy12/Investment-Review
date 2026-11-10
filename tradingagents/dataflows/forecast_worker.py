"""Bounded data-layer entrypoint for third-party forecast clients; no credentials."""

import json
import re
import sys

import pandas as pd


def tables(ticker, market):
    if market == "US":
        import yfinance as yf

        stock = yf.Ticker(ticker)
        frames = [("EPS forecasts", stock.get_earnings_estimate()),
                  ("Revenue forecasts", stock.get_revenue_estimate())]
    else:
        import akshare as ak

        if market == "A_SHARE":
            frames = [("EPS forecasts", ak.stock_profit_forecast_ths(ticker.split(".")[0], "预测年报每股收益")),
                      ("Net profit forecasts", ak.stock_profit_forecast_ths(ticker.split(".")[0], "预测年报净利润"))]
        elif market == "HK":
            frames = [("HK earnings forecasts", ak.stock_hk_profit_forecast_et(ticker.split(".")[0].zfill(5), "综合盈利预测"))]
        else:
            raise ValueError("unsupported_market")
    result = []
    for title, frame in frames:
        if frame is None or frame.empty:
            continue
        metrics = [c for c in frame.columns if c in {"avg", "low", "high", "均值", "最小值", "最大值",
                                                   "纯利/亏损", "每股盈利/每股亏损"}]
        if not metrics:
            continue
        usable = frame[metrics].apply(lambda col: col.map(lambda value: pd.notna(value) and bool(re.search(r"\d", str(value))))).any(axis=1)
        frame = frame[usable]
        if frame.empty:
            continue
        if market == "US":
            frame = frame.rename_axis("forecast_period").reset_index()
        frame = frame.head(8).astype(object).where(pd.notna(frame), None)
        result.append({"title": title, "columns": [str(c) for c in frame.columns], "rows": frame.values.tolist()})
    return result


if __name__ == "__main__":
    print(json.dumps(tables(sys.argv[1], sys.argv[2]), ensure_ascii=False, allow_nan=False, default=str))
