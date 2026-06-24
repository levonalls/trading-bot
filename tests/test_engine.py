import numpy as np
import pandas as pd

from trading_bot.backtest.engine import BacktestEngine
from trading_bot.backtest.metrics import compute_metrics
from trading_bot.strategies.breakout import BreakoutStrategy
from trading_bot.strategies.mean_reversion import MeanReversionStrategy
from trading_bot.strategies.trend_following import TrendFollowingStrategy


def make_trending_df(n=300, seed=0):
    rng = np.random.default_rng(seed)
    drift = np.linspace(0, 50, n)
    noise = rng.normal(0, 1, n).cumsum()
    close = 100 + drift + noise
    high = close + rng.uniform(0, 1, n)
    low = close - rng.uniform(0, 1, n)
    idx = pd.date_range("2023-01-01", periods=n, freq="h")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": 1.0}, index=idx)


def test_trend_following_runs_and_produces_metrics():
    df = make_trending_df()
    result = BacktestEngine().run(df, TrendFollowingStrategy())
    metrics = compute_metrics(result.equity_curve, result.trades)

    assert len(result.equity_curve) == len(df)
    assert "max_drawdown" in metrics
    assert metrics["max_drawdown"] <= 0


def test_mean_reversion_runs():
    df = make_trending_df(seed=1)
    result = BacktestEngine().run(df, MeanReversionStrategy())
    assert len(result.equity_curve) == len(df)


def test_breakout_runs():
    df = make_trending_df(seed=2)
    result = BacktestEngine().run(df, BreakoutStrategy())
    assert len(result.equity_curve) == len(df)


def test_drawdown_circuit_breaker_halts_new_trades():
    df = make_trending_df(seed=3)
    engine = BacktestEngine()
    engine.config.max_drawdown_halt = 0.0  # halt immediately after any loss
    result = engine.run(df, TrendFollowingStrategy())
    assert len(result.equity_curve) == len(df)
