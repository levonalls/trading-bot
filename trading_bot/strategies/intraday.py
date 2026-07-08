from __future__ import annotations

import pandas as pd

"""Shared helpers for intraday (day-trading) strategies.

Day-trading strategies differ from the swing strategies in one structural
way: positions must be flat by the end of each trading session — no
overnight holds. These helpers make that invariant easy to enforce and
test, and keep the per-session iteration pattern consistent across
strategies.
"""


def require_intraday_index(df: pd.DataFrame) -> None:
    """Raise a clear error when data can't support intraday session logic.

    Intraday strategies group bars into sessions by calendar date, which is
    meaningless on daily-or-coarser data or a non-datetime index.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(
            "Intraday strategies need a DatetimeIndex (e.g. from "
            "trading_bot.data.alpaca_data.fetch_stock_bars or load_csv)."
        )
    dates = df.index.normalize()
    if len(df) > 1 and dates.nunique() == len(df):
        raise ValueError(
            "Data looks like daily bars (one bar per date); intraday "
            "strategies need minute/hour bars within each session."
        )


def iter_sessions(df: pd.DataFrame):
    """Yield (session_date, session_df) pairs, one per trading day."""
    return df.groupby(df.index.normalize(), sort=True)


def flatten_session_end(day_signal: list[int], bars: int) -> None:
    """Zero the final `bars` entries of a session's signal, in place.

    This is what enforces "no overnight positions": the backtest engine and
    live runner both close a position when the signal returns to 0.
    """
    for j in range(1, min(bars, len(day_signal)) + 1):
        day_signal[-j] = 0
