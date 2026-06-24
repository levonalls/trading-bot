from __future__ import annotations

import pandas as pd


def fetch_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 1000, exchange: str = "binance") -> pd.DataFrame:
    """Fetch OHLCV candles via ccxt and return a DataFrame indexed by time."""
    import ccxt

    exchange_class = getattr(ccxt, exchange)
    client = exchange_class()
    raw = client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df.set_index("timestamp")


def load_csv(path: str) -> pd.DataFrame:
    """Load OHLCV data from a CSV with a `timestamp` column plus OHLCV columns."""
    df = pd.read_csv(path, parse_dates=["timestamp"])
    return df.set_index("timestamp")
