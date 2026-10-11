from __future__ import annotations

import numpy as np
import pandas as pd

from trading_bot.strategies.breakout import BreakoutStrategy
from trading_bot.strategies.mean_reversion import MeanReversionStrategy
from trading_bot.strategies.trend_following import TrendFollowingStrategy


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index — measures trend strength (not direction)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    dm_plus  = np.where((high - high.shift(1)) > (low.shift(1) - low),
                        np.maximum(high - high.shift(1), 0), 0)
    dm_minus = np.where((low.shift(1) - low) > (high - high.shift(1)),
                        np.maximum(low.shift(1) - low, 0), 0)

    atr      = tr.ewm(span=period, adjust=False).mean()
    di_plus  = 100 * pd.Series(dm_plus,  index=df.index).ewm(span=period, adjust=False).mean() / atr
    di_minus = 100 * pd.Series(dm_minus, index=df.index).ewm(span=period, adjust=False).mean() / atr

    dx = (100 * (di_plus - di_minus).abs() / (di_plus + di_minus + 1e-9))
    return dx.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(span=period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(span=period, adjust=False).mean()
    rs    = gain / (loss + 1e-9)
    return 100 - 100 / (1 + rs)


def _atr_pct(df: pd.DataFrame, period: int = 14) -> float:
    """ATR as a % of price — proxy for current volatility."""
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return float(atr / close.iloc[-1])


class MarketRegime:
    """Snapshot of current market conditions used by the strategy selector."""

    TRENDING    = "trending"
    RANGING     = "ranging"
    BREAKOUT    = "breakout"

    def __init__(self, regime: str, adx: float, atr_pct: float,
                 rsi: float, vol_ratio: float):
        self.regime    = regime
        self.adx       = adx
        self.atr_pct   = atr_pct
        self.rsi       = rsi
        self.vol_ratio = vol_ratio  # recent vol vs. historical vol

    def __repr__(self) -> str:
        return (f"MarketRegime({self.regime}, ADX={self.adx:.1f}, "
                f"ATR%={self.atr_pct*100:.2f}, RSI={self.rsi:.1f}, "
                f"VolRatio={self.vol_ratio:.2f})")


def detect_regime(df: pd.DataFrame) -> MarketRegime:
    """Classify the current market into one of three regimes.

    Trending  — high ADX, moderate volatility.  Best for EMA crossover.
    Ranging   — low ADX, low/moderate vol, RSI cycling.  Best for mean reversion.
    Breakout  — low ADX transitioning + volatility compression then spike.
                Best for Donchian channel breakout.
    """
    if len(df) < 50:
        raise ValueError("Need at least 50 bars to detect regime.")

    adx       = float(_adx(df).iloc[-1])
    atr_pct   = _atr_pct(df)
    rsi       = float(_rsi(df["close"]).iloc[-1])

    # Vol ratio: last-10-bar ATR vs. last-50-bar ATR  (>1.2 = expanding vol)
    recent_vol = float(df["close"].pct_change().rolling(10).std().iloc[-1])
    hist_vol   = float(df["close"].pct_change().rolling(50).std().iloc[-1])
    vol_ratio  = recent_vol / (hist_vol + 1e-9)

    # Classification rules
    if adx >= 25:
        regime = MarketRegime.TRENDING
    elif vol_ratio < 0.8:
        # Volatility squeeze — breakout likely incoming
        regime = MarketRegime.BREAKOUT
    else:
        regime = MarketRegime.RANGING

    return MarketRegime(regime, adx, atr_pct, rsi, vol_ratio)


def select_strategy(df: pd.DataFrame):
    """Detect the current regime and return the most suitable strategy instance.

    Returns (strategy, regime) so the caller can log which was chosen and why.
    """
    regime = detect_regime(df)

    if regime.regime == MarketRegime.TRENDING:
        strategy = TrendFollowingStrategy()
    elif regime.regime == MarketRegime.BREAKOUT:
        strategy = BreakoutStrategy()
    else:
        strategy = MeanReversionStrategy()

    return strategy, regime
