from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pandas as pd

ALPACA_DATA_URL = "https://data.alpaca.markets"

# Minutes per bar for supported Alpaca timeframe strings.
_TIMEFRAME_MINUTES = {
    "1Min": 1,
    "5Min": 5,
    "15Min": 15,
    "30Min": 30,
    "1Hour": 60,
    "1Day": 60 * 24,
}


def _default_start(timeframe: str, limit: int, now: datetime) -> datetime:
    """Estimate how far back to query to collect `limit` bars.

    Equities only print bars during market hours, so calendar time per bar
    is several times the bar interval (390 trading minutes in a 1440-minute
    day, plus weekends/holidays). A 6x buffer overshoots on purpose — extra
    rows are trimmed, missing rows are not recoverable.
    """
    minutes = _TIMEFRAME_MINUTES[timeframe]
    buffer = 2 if timeframe == "1Day" else 6
    return now - timedelta(minutes=minutes * limit * buffer)


def fetch_stock_bars(
    symbol: str,
    timeframe: str = "5Min",
    limit: int = 2000,
    feed: str = "iex",
    start: str | None = None,
    end: str | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
    client=None,
) -> pd.DataFrame:
    """Fetch stock OHLCV bars from Alpaca's Market Data API.

    Returns a DataFrame shaped like `fetch_ohlcv` (timestamp index +
    open/high/low/close/volume), with the index converted to US/Eastern so
    the intraday strategies' session grouping lines up with market days.

    The default `feed="iex"` is free with any Alpaca account (paper
    accounts included) — set ALPACA_API_KEY / ALPACA_API_SECRET. Accounts
    with a market-data subscription can pass feed="sip" for full-market
    coverage.
    """
    import httpx

    if timeframe not in _TIMEFRAME_MINUTES:
        raise ValueError(f"Unsupported timeframe {timeframe!r}; use one of {sorted(_TIMEFRAME_MINUTES)}")

    api_key = api_key or os.environ.get("ALPACA_API_KEY")
    api_secret = api_secret or os.environ.get("ALPACA_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError(
            "Alpaca credentials missing: set ALPACA_API_KEY and ALPACA_API_SECRET "
            "(free keys at https://alpaca.markets)."
        )
    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}

    now = datetime.now(timezone.utc)
    params: dict = {
        "timeframe": timeframe,
        "feed": feed,
        "adjustment": "split",
        "start": start or _default_start(timeframe, limit, now).isoformat(),
    }
    if end:
        params["end"] = end

    own_client = client is None
    client = client or httpx.Client(timeout=30)
    bars: list[dict] = []
    try:
        page_token = None
        while True:
            page_params = {**params, "limit": min(10_000, limit)}
            if page_token:
                page_params["page_token"] = page_token
            resp = client.get(f"{ALPACA_DATA_URL}/v2/stocks/{symbol}/bars", params=page_params, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
            bars.extend(payload.get("bars") or [])
            page_token = payload.get("next_page_token")
            if not page_token:
                break
    finally:
        if own_client:
            client.close()

    if not bars:
        raise RuntimeError(f"Alpaca returned no bars for {symbol} ({timeframe}, feed={feed}).")

    df = pd.DataFrame(
        {
            "timestamp": [b["t"] for b in bars],
            "open": [b["o"] for b in bars],
            "high": [b["h"] for b in bars],
            "low": [b["l"] for b in bars],
            "close": [b["c"] for b in bars],
            "volume": [b["v"] for b in bars],
        }
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("America/New_York")
    return df.set_index("timestamp").tail(limit)
