import numpy as np
import pandas as pd

from trading_bot.screen_stocks import classify, screen_stocks


def make_daily_df(closes: np.ndarray) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
            "volume": 1_000_000.0,
        },
        index=idx,
    )


def synthetic_universe(symbol: str, timeframe: str = "1Day", limit: int = 120) -> pd.DataFrame:
    n = 120
    if symbol == "UPTREND_PULLBACK":
        closes = np.linspace(100, 160, n)
        closes[-5:] = closes[-5:] * np.linspace(1.0, 0.96, 5)  # 4% off the highs
    elif symbol == "BREAKOUT":
        closes = np.linspace(100, 150, n)  # closing at its high
    elif symbol == "DOWNTREND":
        closes = np.linspace(150, 100, n)
    elif symbol == "NO_DATA":
        raise RuntimeError("no bars")
    else:
        closes = np.full(n, 100.0)
    return make_daily_df(closes)


def test_screen_ranks_setups_above_no_setup():
    results = screen_stocks(
        ["UPTREND_PULLBACK", "BREAKOUT", "DOWNTREND", "FLAT", "NO_DATA"],
        fetch_fn=synthetic_universe,
    )
    symbols = [r.symbol for r in results]

    assert "NO_DATA" not in symbols  # failed fetch skipped, not fatal
    assert symbols[0] in ("UPTREND_PULLBACK", "BREAKOUT")
    assert results[0].setup != "no_setup"

    downtrend = next(r for r in results if r.symbol == "DOWNTREND")
    assert downtrend.trend == "down"
    assert downtrend.setup == "no_setup"


def test_classify_trend_pullback():
    closes = pd.Series(np.linspace(100, 160, 120))
    setup, score = classify(closes, r=45, dist_high=-0.04, trend="up")
    assert setup == "trend_pullback"
    assert score > 2


def test_classify_downtrend_is_no_setup():
    closes = pd.Series(np.linspace(160, 100, 120))
    setup, _ = classify(closes, r=45, dist_high=-0.20, trend="down")
    assert setup == "no_setup"
