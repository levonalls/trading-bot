from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trading_bot.strategies.base import Strategy, StrategyParams


@dataclass
class BreakoutParams(StrategyParams):
    entry_window: int = 20
    exit_window: int = 10


class BreakoutStrategy(Strategy):
    """Donchian channel breakout ("turtle trading" style).

    Long on a close above the N-bar high, short on a close below the
    N-bar low, flat once price crosses back through the shorter exit
    channel.
    """

    name = "breakout"

    def __init__(self, params: BreakoutParams | None = None):
        super().__init__(params or BreakoutParams())

    def signals(self, df: pd.DataFrame) -> pd.Series:
        p: BreakoutParams = self.params
        high, low, close = df["high"], df["low"], df["close"]

        entry_high = high.rolling(p.entry_window).max()
        entry_low = low.rolling(p.entry_window).min()
        exit_high = high.rolling(p.exit_window).max()
        exit_low = low.rolling(p.exit_window).min()

        signal = pd.Series(0, index=df.index)
        position = 0
        for i in range(len(df)):
            if position == 0:
                if close.iloc[i] >= entry_high.iloc[i - 1] if i > 0 else False:
                    position = 1
                elif close.iloc[i] <= entry_low.iloc[i - 1] if i > 0 else False:
                    position = -1
            elif position == 1 and i > 0 and close.iloc[i] <= exit_low.iloc[i - 1]:
                position = 0
            elif position == -1 and i > 0 and close.iloc[i] >= exit_high.iloc[i - 1]:
                position = 0
            signal.iloc[i] = position
        return signal
