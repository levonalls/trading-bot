from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trading_bot.strategies.base import Strategy, StrategyParams
from trading_bot.strategies.intraday import flatten_session_end, iter_sessions, require_intraday_index


@dataclass
class VwapReversionParams(StrategyParams):
    stop_loss_pct: float = 0.01
    take_profit_pct: float = 0.015
    band_pct: float = 0.005  # entry when price stretches this far from session VWAP
    warmup_bars: int = 3  # skip the first bars of each session while VWAP stabilizes
    eod_flat_bars: int = 1


class VwapReversionStrategy(Strategy):
    """Mean reversion to the session VWAP.

    VWAP is the intraday anchor institutional flow executes against, which
    is why stretched moves away from it tend to snap back. Long when price
    trades `band_pct` below the session's running VWAP, short when it
    trades that far above, and exit when price tags VWAP again. Flat
    overnight; VWAP resets every session.
    """

    name = "vwap_reversion"

    def __init__(self, params: VwapReversionParams | None = None):
        super().__init__(params or VwapReversionParams())

    def signals(self, df: pd.DataFrame) -> pd.Series:
        require_intraday_index(df)
        p: VwapReversionParams = self.params

        signal = pd.Series(0, index=df.index)
        for _, day in iter_sessions(df):
            n = len(day)
            if n <= p.warmup_bars:
                continue
            typical = (day["high"] + day["low"] + day["close"]) / 3
            cum_volume = day["volume"].cumsum()
            # Zero cumulative volume (e.g. a dead pre-open bar) would divide
            # by zero; treat VWAP as undefined there and take no signal.
            vwap = (typical * day["volume"]).cumsum() / cum_volume.where(cum_volume > 0)

            close = day["close"]
            position = 0
            day_signal = [0] * n
            for i in range(p.warmup_bars, n):
                v = vwap.iloc[i]
                if pd.isna(v):
                    day_signal[i] = position
                    continue
                c = close.iloc[i]
                if position == 0:
                    if c <= v * (1 - p.band_pct):
                        position = 1
                    elif c >= v * (1 + p.band_pct):
                        position = -1
                elif position == 1 and c >= v:
                    position = 0
                elif position == -1 and c <= v:
                    position = 0
                day_signal[i] = position
            flatten_session_end(day_signal, p.eod_flat_bars)
            signal.loc[day.index] = day_signal
        return signal
