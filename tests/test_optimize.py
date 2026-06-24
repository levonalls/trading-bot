import numpy as np
import pandas as pd

from trading_bot.backtest.optimize import grid_search
from trading_bot.backtest.param_grids import make_factory
from trading_bot.backtest.walk_forward import summarize_windows, walk_forward_optimize


def make_trending_df(n=600, seed=0):
    rng = np.random.default_rng(seed)
    drift = np.linspace(0, 100, n)
    noise = rng.normal(0, 1, n).cumsum()
    close = 100 + drift + noise
    high = close + rng.uniform(0, 1, n)
    low = close - rng.uniform(0, 1, n)
    idx = pd.date_range("2023-01-01", periods=n, freq="h")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": 1.0}, index=idx)


def test_grid_search_ranks_results():
    df = make_trending_df()
    factory = make_factory("trend_following")
    small_grid = {
        "fast_ema": [10, 20],
        "slow_ema": [40, 50],
        "trend_ema": [200],
        "stop_loss_pct": [0.02],
        "take_profit_pct": [0.06],
    }
    results = grid_search(df, factory, small_grid)
    assert len(results) == 4
    assert results["score"].is_monotonic_decreasing


def test_walk_forward_optimize_produces_windows():
    df = make_trending_df(n=400)
    factory = make_factory("breakout")
    small_grid = {
        "entry_window": [10, 20],
        "exit_window": [5, 10],
        "stop_loss_pct": [0.02],
        "take_profit_pct": [0.06],
    }
    windows = walk_forward_optimize(df, factory, small_grid, train_bars=150, test_bars=50)
    assert len(windows) >= 1
    summary = summarize_windows(windows)
    assert summary["num_windows"] == len(windows)
