from __future__ import annotations

import pandas as pd


def fetch_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 1000, exchange: str = "binance") -> pd.DataFrame:
    """Fetch OHLCV candles via ccxt and return a DataFrame indexed by time.

    Paginates backward in time when the exchange caps candles per call below
    `limit` (e.g. Coinbase returns at most ~300 regardless of the requested
    limit), so callers asking for 1000 bars actually get 1000 bars.
    """
    import ccxt

    exchange_class = getattr(ccxt, exchange)
    client = exchange_class()
    timeframe_ms = client.parse_timeframe(timeframe) * 1000

    since = client.milliseconds() - timeframe_ms * limit
    candles: list = []
    while len(candles) < limit:
        batch = client.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit - len(candles))
        if not batch:
            break
        candles.extend(batch)
        next_since = batch[-1][0] + timeframe_ms
        if next_since <= since:
            break
        since = next_since

    candles = candles[-limit:]
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df.set_index("timestamp")


def load_csv(path: str) -> pd.DataFrame:
    """Load OHLCV data from a CSV with a `timestamp` column plus OHLCV columns."""
    df = pd.read_csv(path, parse_dates=["timestamp"])
    return df.set_index("timestamp")
