from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trading_bot.strategies.base import Strategy, StrategyParams
from trading_bot.strategies.intraday import flatten_session_end, iter_sessions, require_intraday_index


@dataclass
class GapAndGoParams(StrategyParams):
    stop_loss_pct: float = 0.015
    take_profit_pct: float = 0.03
    min_gap_pct: float = 0.02  # session open must gap at least this far from prior close
    confirm_bars: int = 1  # bars the gap must hold before entering
    eod_flat_bars: int = 1


class GapAndGoStrategy(Strategy):
    """Gap-and-go momentum, the classic open-drive day trade.

    When a session opens gapped up at least `min_gap_pct` above the prior
    session's close and price is still above the session open after
    `confirm_bars` bars (the gap is holding, not fading), go long and ride
    the momentum. The trade is invalidated — back to flat — if price
    closes below the session open, since a filled gap is the failure mode.
    Gap-downs are traded short symmetrically. One trade per session, flat
    overnight.
    """

    name = "gap_and_go"

    def __init__(self, params: GapAndGoParams | None = None):
        super().__init__(params or GapAndGoParams())

    def signals(self, df: pd.DataFrame) -> pd.Series:
        require_intraday_index(df)
        p: GapAndGoParams = self.params

        signal = pd.Series(0, index=df.index)
        prev_close: float | None = None
        for _, day in iter_sessions(df):
            n = len(day)
            close = day["close"]
            session_open = day["open"].iloc[0]

            direction = 0
            if prev_close is not None and prev_close > 0:
                gap = session_open / prev_close - 1
                if gap >= p.min_gap_pct:
                    direction = 1
                elif gap <= -p.min_gap_pct:
                    direction = -1
            prev_close = close.iloc[-1]
            if direction == 0:
                continue

            position = 0
            traded = False
            day_signal = [0] * n
            for i in range(p.confirm_bars, n):
                c = close.iloc[i]
                gap_holding = c > session_open if direction == 1 else c < session_open
                if position == 0 and not traded and gap_holding:
                    position = direction
                    traded = True
                elif position != 0 and not gap_holding:
                    position = 0  # gap is filling: momentum thesis is dead
                day_signal[i] = position
            flatten_session_end(day_signal, p.eod_flat_bars)
            signal.loc[day.index] = day_signal
        return signal
