from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trading_bot.strategies.base import Strategy, StrategyParams


@dataclass
class TrendFollowingParams(StrategyParams):
    fast_ema: int = 20
    slow_ema: int = 50
    trend_ema: int = 200


class TrendFollowingStrategy(Strategy):
    """EMA crossover filtered by a long-term trend EMA.

    Long when fast EMA > slow EMA and price is above the trend EMA;
    short in the mirror case. This is the backbone of most systematic
    trend-following CTAs.
    """

    name = "trend_following"

    def __init__(self, params: TrendFollowingParams | None = None):
        super().__init__(params or TrendFollowingParams())

    def signals(self, df: pd.DataFrame) -> pd.Series:
        p: TrendFollowingParams = self.params
        close = df["close"]
        fast = close.ewm(span=p.fast_ema, adjust=False).mean()
        slow = close.ewm(span=p.slow_ema, adjust=False).mean()
        trend = close.ewm(span=p.trend_ema, adjust=False).mean()

        long_cond = (fast > slow) & (close > trend)
        short_cond = (fast < slow) & (close < trend)

        signal = pd.Series(0, index=df.index)
        signal[long_cond] = 1
        signal[short_cond] = -1
        return signal
