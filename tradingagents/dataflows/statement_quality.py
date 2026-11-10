"""Period checks for opt-in statement routing; never infer currencies or quarters."""

import io
import json
import re
from contextlib import suppress
from datetime import date

import pandas as pd

from tradingagents.dataflows.date_window import get_current_date, is_historical
from tradingagents.dataflows.errors import NoMarketDataError

METHODS = {"get_balance_sheet", "get_income_statement", "get_cashflow"}


def market_for(ticker):
    ticker = str(ticker).upper()
    return "HK" if ticker.endswith(".HK") else "A_SHARE" if ticker.endswith((".SS", ".SZ")) else "US"


def policy_for(method, args, kwargs, config):
    policy = config.get("statement_freshness", {})
    if method not in METHODS or not policy.get("enabled"):
        return None
    ticker = args[0] if args else kwargs.get("ticker", "")
    cutoff = (args[2] if len(args) > 2 else kwargs.get("as_of_date")) or get_current_date()
    # As-filed historical selection remains the vendor's responsibility. Never
    # compare an archived SEC vintage with current secondary-provider snapshots.
    if is_historical(cutoff):
        return None
    result = {**policy, "ticker": ticker, "as_of": cutoff, "market": market_for(ticker),
              "frequency": args[1] if len(args) > 1 else kwargs.get("freq", "quarterly")}
    # The shared packet is produced before the graph runs. Only exact ISO dates
    # from the official full-report extractor can tighten the period floor.
    try:
        packet = json.loads(config.get("shared_research_evidence", "").split("```json\n", 1)[1].rsplit("\n```", 1)[0])
        periods = [item["period"] for item in packet["items"]
                   if item.get("source") == "HKEX issuer filing" and item.get("financial_report")
                   and re.fullmatch(r"\d{4}-\d{2}-\d{2}", item.get("period", ""))]
        if periods and result["frequency"] != "annual":
            result["official_reference_period"] = max(periods)
    except (ValueError, KeyError, IndexError, TypeError):
        pass
    return result


def statement_periods(text):
    """Read dates from table axes only, not retrieval dates in prose headers."""
    frame = pd.read_csv(io.StringIO(text), comment="#", dtype=str)
    values = [column for column in frame if re.match(r"^\d{4}-\d{2}-\d{2}", column)
              and pd.to_numeric(frame[column], errors="coerce").notna().any()]
    metadata = {"REPORT_DATE", "Period", "START_DATE", "STD_REPORT_DATE", "NOTICE_DATE", "UPDATE_DATE",
                "SECUCODE", "SECURITY_CODE", "SECURITY_NAME_ABBR", "ORG_CODE", "STD_ITEM_CODE",
                "DATE_TYPE_CODE", "FISCAL_YEAR", "REPORT_TYPE"}
    amounts = frame[["AMOUNT"]] if "AMOUNT" in frame else frame.drop(columns=list(metadata), errors="ignore")
    usable = amounts.apply(pd.to_numeric, errors="coerce").notna().any(axis=1)
    for column in ("REPORT_DATE", "Period"):
        if column in frame:
            values.extend(frame.loc[usable, column].dropna())
    periods = []
    for value in values:
        match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:$|[ T(])", str(value))
        if match:
            with suppress(ValueError):
                periods.append(date.fromisoformat(match[1]).isoformat())
    return sorted(set(periods))


def _reject(policy, vendor, reason, **metadata):
    error = NoMarketDataError(policy["ticker"], detail=f"{vendor}: {reason}")
    error.statement_observation = {"vendor": vendor, "status": "rejected", "reason": reason, **metadata}
    raise error


def assess(text, vendor, policy):
    if not isinstance(text, str) or text.startswith(("DATA_UNAVAILABLE", "NO_DATA_AVAILABLE")):
        _reject(policy, vendor, "statement unavailable")
    try:
        periods = statement_periods(text)
    except (ValueError, pd.errors.ParserError):
        periods = []
    if not periods:
        _reject(policy, vendor, "statement period UNKNOWN")
    latest = periods[-1]
    if latest > policy["as_of"]:
        _reject(policy, vendor, "future statement period", latest_period=latest)
    if latest < policy.get("official_reference_period", ""):
        _reject(policy, vendor, f"{latest} precedes official report {policy['official_reference_period']}", latest_period=latest)
    age = (date.fromisoformat(policy["as_of"]) - date.fromisoformat(latest)).days
    limit = (policy.get("annual_max_age_days", 550) if policy["frequency"] == "annual"
             else policy.get("max_age_days", {}).get(policy["market"], 275))
    if age > limit:
        _reject(policy, vendor, f"latest period {latest} is {age} days old; limit {limit}", latest_period=latest, period_age_days=age)
    return {"vendor": vendor, "latest_period": latest, "period_age_days": age}


def select(candidates, observations, policy):
    # max is stable: configured priority wins ties. Do not merge monetary values
    # across providers or treat a newer table as proof of accounting comparability.
    chosen = max(candidates, key=lambda row: row[0]["latest_period"])
    metadata = {**chosen[0], "as_of": policy["as_of"], "observations": observations,
                "official_reference_period": policy.get("official_reference_period", "UNKNOWN"),
                "coverage": "latest among successful configured vendors checked; official reference, if present, comes from bounded discovery, not an exhaustive archive",
                "currency_rule": "Use explicit table currency/unit only; listing or quote currency is not evidence."}
    return "# Statement freshness: " + json.dumps(metadata, ensure_ascii=False) + "\n" + chosen[1]
