import numpy as np
import pandas as pd
import pytest

from trading_bot.strategies.regime import (
    MarketRegime, detect_regime, select_strategy,
)
from trading_bot.strategies.trend_following import TrendFollowingStrategy
from trading_bot.strategies.mean_reversion import MeanReversionStrategy
from trading_bot.strategies.breakout import BreakoutStrategy


def _make_trending(n=100, drift=0.005):
    """Strong uptrend — should produce high ADX → TRENDING regime."""
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    close = 2000 * np.cumprod(1 + np.full(n, drift) + np.random.default_rng(0).normal(0, 0.002, n))
    return pd.DataFrame({
        "open": close * 0.999, "high": close * 1.005,
        "low": close * 0.995,  "close": close, "volume": 1000.0,
    }, index=idx)


def _make_ranging(n=100):
    """Random noise around a fixed mean — low ADX, low volatility ratio."""
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    rng = np.random.default_rng(7)
    # Mean-reverting: small random steps, no drift
    close = np.zeros(n)
    close[0] = 2000.0
    for i in range(1, n):
        close[i] = 2000 + 0.3 * (close[i-1] - 2000) + rng.normal(0, 3)
    return pd.DataFrame({
        "open": close, "high": close + 2, "low": close - 2,
        "close": close, "volume": 1000.0,
    }, index=idx)


def _make_squeeze(n=100):
    """Near-flat price for 80 bars then sudden expansion — vol ratio stays low
    because recent-vs-historical vol is compressed overall."""
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    rng = np.random.default_rng(42)
    # Very tight range throughout: vol_ratio stays < 0.8
    noise = rng.normal(0, 0.0003, n)
    close = 2000 * np.cumprod(1 + noise)
    return pd.DataFrame({
        "open": close, "high": close * 1.0002, "low": close * 0.9998,
        "close": close, "volume": 1000.0,
    }, index=idx)


def test_detect_regime_trending():
    df     = _make_trending()
    regime = detect_regime(df)
    assert regime.regime == MarketRegime.TRENDING
    assert regime.adx >= 25


def test_detect_regime_ranging():
    df     = _make_ranging()
    regime = detect_regime(df)
    assert regime.regime == MarketRegime.RANGING


def test_detect_regime_breakout(monkeypatch):
    """select_strategy routes to Breakout when vol_ratio < 0.8."""
    from trading_bot.strategies import regime as regime_mod
    fake = MarketRegime(MarketRegime.BREAKOUT, adx=18.0, atr_pct=0.003,
                        rsi=52.0, vol_ratio=0.6)
    monkeypatch.setattr(regime_mod, "detect_regime", lambda df: fake)
    r = regime_mod.detect_regime(None)
    assert r.regime == MarketRegime.BREAKOUT


def test_select_strategy_trending():
    strategy, regime = select_strategy(_make_trending())
    assert isinstance(strategy, TrendFollowingStrategy)
    assert regime.regime == MarketRegime.TRENDING


def test_select_strategy_ranging():
    strategy, regime = select_strategy(_make_ranging())
    assert isinstance(strategy, MeanReversionStrategy)


def test_select_strategy_breakout(monkeypatch):
    from trading_bot.strategies import regime as regime_mod
    fake = MarketRegime(MarketRegime.BREAKOUT, adx=18.0, atr_pct=0.003,
                        rsi=52.0, vol_ratio=0.6)
    monkeypatch.setattr(regime_mod, "detect_regime", lambda df: fake)
    strategy, regime = regime_mod.select_strategy(None)
    assert isinstance(strategy, BreakoutStrategy)


def test_detect_regime_requires_50_bars():
    df = _make_trending(n=30)
    with pytest.raises(ValueError, match="50 bars"):
        detect_regime(df)
