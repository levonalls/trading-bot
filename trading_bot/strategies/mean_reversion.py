from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trading_bot.strategies.base import Strategy, StrategyParams


@dataclass
class MeanReversionParams(StrategyParams):
    bb_window: int = 20
    bb_std: float = 2.0
    rsi_window: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0


def _rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


class MeanReversionStrategy(Strategy):
    """Bollinger Band + RSI mean reversion.

    Long when price closes below the lower band while RSI is oversold;
    short when it closes above the upper band while RSI is overbought.
    Exits when price reverts to the middle band (handled by the engine
    via take-profit/stop-loss, not modeled here as a third state).
    """

    name = "mean_reversion"

    def __init__(self, params: MeanReversionParams | None = None):
        super().__init__(params or MeanReversionParams())

    def signals(self, df: pd.DataFrame) -> pd.Series:
        p: MeanReversionParams = self.params
        close = df["close"]
        mid = close.rolling(p.bb_window).mean()
        std = close.rolling(p.bb_window).std()
        upper = mid + p.bb_std * std
        lower = mid - p.bb_std * std
        rsi = _rsi(close, p.rsi_window)

        long_cond = (close < lower) & (rsi < p.rsi_oversold)
        short_cond = (close > upper) & (rsi > p.rsi_overbought)

        signal = pd.Series(0, index=df.index)
        signal[long_cond] = 1
        signal[short_cond] = -1
        return signal
