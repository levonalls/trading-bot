from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trading_bot.strategies.base import Strategy, StrategyParams
from trading_bot.strategies.intraday import flatten_session_end, iter_sessions, require_intraday_index


@dataclass
class OpeningRangeBreakoutParams(StrategyParams):
    # Day-trade scale: stops/targets are much tighter than the swing defaults.
    stop_loss_pct: float = 0.01
    take_profit_pct: float = 0.02
    range_bars: int = 3  # bars that define the opening range (3 x 5min = 15min)
    eod_flat_bars: int = 1  # force flat this many bars before session end


class OpeningRangeBreakoutStrategy(Strategy):
    """Opening-range breakout (ORB), the canonical equities day-trade.

    The high/low of the first `range_bars` bars of each session define the
    opening range. A close above the range high goes long, a close below
    the range low goes short; the position is held until the engine's
    stop/take-profit fires or the session ends. One directional commitment
    per day — no flip-flopping after the first breakout — and always flat
    overnight.
    """

    name = "opening_range_breakout"

    def __init__(self, params: OpeningRangeBreakoutParams | None = None):
        super().__init__(params or OpeningRangeBreakoutParams())

    def signals(self, df: pd.DataFrame) -> pd.Series:
        require_intraday_index(df)
        p: OpeningRangeBreakoutParams = self.params

        signal = pd.Series(0, index=df.index)
        for _, day in iter_sessions(df):
            n = len(day)
            if n <= p.range_bars:
                continue
            range_high = day["high"].iloc[: p.range_bars].max()
            range_low = day["low"].iloc[: p.range_bars].min()

            close = day["close"]
            position = 0
            day_signal = [0] * n
            for i in range(p.range_bars, n):
                if position == 0:
                    if close.iloc[i] > range_high:
                        position = 1
                    elif close.iloc[i] < range_low:
                        position = -1
                day_signal[i] = position
            flatten_session_end(day_signal, p.eod_flat_bars)
            signal.loc[day.index] = day_signal
        return signal
