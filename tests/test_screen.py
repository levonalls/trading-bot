from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from trading_bot.screen import score_summary, screen, top_coinbase_symbols


def make_df(n, seed):
    rng = np.random.default_rng(seed)
    drift = np.linspace(0, 60, n)
    noise = rng.normal(0, 1, n).cumsum()
    close = 100 + drift + noise
    high = close + rng.uniform(0, 1, n)
    low = close - rng.uniform(0, 1, n)
    idx = pd.date_range("2023-01-01", periods=n, freq="h")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": 1.0}, index=idx)


def test_top_coinbase_symbols_ranks_by_volume_and_excludes_stablecoins():
    fake_client = MagicMock()
    fake_client.fetch_tickers.return_value = {
        "BTC/USD": {"quoteVolume": 1000},
        "ETH/USD": {"quoteVolume": 2000},
        "USDC/USD": {"quoteVolume": 5000},  # excluded: stablecoin base
        "SOL/EUR": {"quoteVolume": 9000},  # excluded: wrong quote
    }

    with patch("ccxt.coinbase", return_value=fake_client):
        symbols = top_coinbase_symbols("coinbase", "USD", limit=5)

    assert symbols == ["ETH/USD", "BTC/USD"]


def test_score_summary_penalizes_drawdown():
    good = score_summary({"compounded_oos_return": 0.1, "worst_oos_drawdown": -0.02, "avg_oos_sharpe": 1, "avg_oos_return": 0.1, "num_windows": 2})
    bad = score_summary({"compounded_oos_return": 0.1, "worst_oos_drawdown": -0.5, "avg_oos_sharpe": 1, "avg_oos_return": 0.1, "num_windows": 2})
    assert good > bad


def test_screen_ranks_and_dedupes_by_symbol(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dfs = {
        "BTC/USD": make_df(900, seed=0),
        "ETH/USD": make_df(900, seed=1),
    }

    with patch("trading_bot.screen.top_coinbase_symbols", return_value=list(dfs.keys())), \
         patch("trading_bot.screen.fetch_ohlcv", side_effect=lambda symbol, **kw: dfs[symbol]):
        top = screen(num_candidates=2, top_n=2, train_bars=600, test_bars=150)

    symbols_seen = {r.symbol for r in top}
    assert symbols_seen == set(dfs.keys())
    assert len(top) == 2
