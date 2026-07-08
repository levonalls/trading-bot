import numpy as np
import pandas as pd
import pytest

from trading_bot.backtest.engine import BacktestEngine
from trading_bot.strategies.gap_and_go import GapAndGoParams, GapAndGoStrategy
from trading_bot.strategies.opening_range_breakout import (
    OpeningRangeBreakoutParams,
    OpeningRangeBreakoutStrategy,
)
from trading_bot.strategies.vwap_reversion import VwapReversionParams, VwapReversionStrategy

BARS_PER_SESSION = 78  # 5-minute bars, 09:30 -> 16:00


def make_session_index(days=3, start="2024-01-08"):
    """5-min bar timestamps over consecutive weekday sessions."""
    dates = pd.bdate_range(start, periods=days)
    stamps = []
    for d in dates:
        stamps.extend(pd.date_range(d + pd.Timedelta(hours=9, minutes=30), periods=BARS_PER_SESSION, freq="5min"))
    return pd.DatetimeIndex(stamps)


def df_from_close(close: np.ndarray, index: pd.DatetimeIndex, volume: float = 1000.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.05,
            "low": close - 0.05,
            "close": close,
            "volume": volume,
        },
        index=index,
    )


def make_intraday_df(days=3, seed=0, drift_per_bar=0.0):
    rng = np.random.default_rng(seed)
    idx = make_session_index(days)
    close = 100 + np.arange(len(idx)) * drift_per_bar + rng.normal(0, 0.1, len(idx)).cumsum()
    return df_from_close(close, idx)


def assert_flat_overnight(signal: pd.Series):
    last_bars = signal.groupby(signal.index.normalize()).tail(1)
    assert (last_bars == 0).all(), "intraday strategy held a position into the close"


# ---- opening range breakout ----


def test_orb_goes_long_on_breakout_and_flattens_eod():
    idx = make_session_index(days=1)
    close = np.full(BARS_PER_SESSION, 100.0)
    close[10:] = 102.0  # clean break above the opening range
    df = df_from_close(close, idx)

    strategy = OpeningRangeBreakoutStrategy(OpeningRangeBreakoutParams(range_bars=3))
    signal = strategy.signals(df)

    assert (signal.iloc[:3] == 0).all()  # no position while the range forms
    assert signal.iloc[15] == 1
    assert_flat_overnight(signal)


def test_orb_goes_short_on_breakdown():
    idx = make_session_index(days=1)
    close = np.full(BARS_PER_SESSION, 100.0)
    close[10:] = 98.0
    df = df_from_close(close, idx)

    signal = OpeningRangeBreakoutStrategy(OpeningRangeBreakoutParams(range_bars=3)).signals(df)
    assert signal.iloc[15] == -1
    assert_flat_overnight(signal)


def test_orb_commits_to_one_direction_per_day():
    idx = make_session_index(days=1)
    close = np.full(BARS_PER_SESSION, 100.0)
    close[10:20] = 102.0
    close[20:] = 95.0  # reversal through the range low must not flip the position
    df = df_from_close(close, idx)

    signal = OpeningRangeBreakoutStrategy(OpeningRangeBreakoutParams(range_bars=3)).signals(df)
    assert set(signal.unique()) <= {0, 1}


def test_intraday_strategy_rejects_daily_data():
    idx = pd.date_range("2024-01-01", periods=50, freq="D")
    df = df_from_close(np.linspace(100, 110, 50), idx)
    with pytest.raises(ValueError, match="daily"):
        OpeningRangeBreakoutStrategy().signals(df)


# ---- VWAP reversion ----


def test_vwap_reversion_buys_the_dip_and_exits_at_vwap():
    idx = make_session_index(days=1)
    close = np.full(BARS_PER_SESSION, 100.0)
    close[10:15] = 99.0  # ~1% below the running VWAP -> long entry
    df = df_from_close(close, idx)

    strategy = VwapReversionStrategy(VwapReversionParams(band_pct=0.005, warmup_bars=3))
    signal = strategy.signals(df)

    assert signal.iloc[12] == 1
    assert signal.iloc[20] == 0  # price back at VWAP -> exit
    assert_flat_overnight(signal)


def test_vwap_reversion_shorts_the_stretch_above():
    idx = make_session_index(days=1)
    close = np.full(BARS_PER_SESSION, 100.0)
    close[10:15] = 101.2
    df = df_from_close(close, idx)

    signal = VwapReversionStrategy(VwapReversionParams(band_pct=0.005, warmup_bars=3)).signals(df)
    assert signal.iloc[12] == -1
    assert_flat_overnight(signal)


def test_vwap_handles_zero_volume_bars():
    idx = make_session_index(days=1)
    close = np.full(BARS_PER_SESSION, 100.0)
    df = df_from_close(close, idx, volume=0.0)
    signal = VwapReversionStrategy().signals(df)
    assert (signal == 0).all()


# ---- gap and go ----


def make_gap_df(gap_pct: float):
    """Two sessions: flat day one; day two opens gapped by gap_pct and the
    gap holds (price keeps drifting away from the session open)."""
    idx = make_session_index(days=2)
    close = np.full(2 * BARS_PER_SESSION, 100.0)
    gapped = 100.0 * (1 + gap_pct)
    drift = 1 if gap_pct >= 0 else -1
    close[BARS_PER_SESSION:] = gapped + drift * np.linspace(0, 0.5, BARS_PER_SESSION)
    return df_from_close(close, idx)


def test_gap_and_go_longs_a_holding_gap_up():
    df = make_gap_df(0.03)
    signal = GapAndGoStrategy(GapAndGoParams(min_gap_pct=0.02, confirm_bars=1)).signals(df)

    assert (signal.iloc[:BARS_PER_SESSION] == 0).all()  # no prior close on day one
    day2 = signal.iloc[BARS_PER_SESSION:]
    assert (day2.iloc[2:-1] == 1).all()
    assert_flat_overnight(signal)


def test_gap_and_go_shorts_a_gap_down():
    df = make_gap_df(-0.03)
    signal = GapAndGoStrategy(GapAndGoParams(min_gap_pct=0.02, confirm_bars=1)).signals(df)
    assert signal.iloc[BARS_PER_SESSION + 5] == -1


def test_gap_and_go_ignores_small_gaps():
    df = make_gap_df(0.005)
    signal = GapAndGoStrategy(GapAndGoParams(min_gap_pct=0.02)).signals(df)
    assert (signal == 0).all()


def test_gap_and_go_exits_when_gap_fills():
    idx = make_session_index(days=2)
    close = np.full(2 * BARS_PER_SESSION, 100.0)
    close[BARS_PER_SESSION] = 103.0  # day two opens gapped up 3%
    close[BARS_PER_SESSION + 1 :] = 103.2  # gap holds above the 103 open...
    close[BARS_PER_SESSION + 30 :] = 102.0  # ...until it fills: below the open
    df = df_from_close(close, idx)

    signal = GapAndGoStrategy(GapAndGoParams(min_gap_pct=0.02, confirm_bars=1)).signals(df)
    assert signal.iloc[BARS_PER_SESSION + 5] == 1
    assert (signal.iloc[BARS_PER_SESSION + 30 :] == 0).all()  # out, and no re-entry


# ---- engine integration ----


def test_intraday_strategies_run_through_backtest_engine():
    df = make_intraday_df(days=5, seed=42, drift_per_bar=0.02)
    for strategy in (OpeningRangeBreakoutStrategy(), VwapReversionStrategy(), GapAndGoStrategy()):
        result = BacktestEngine().run(df, strategy)
        assert len(result.equity_curve) == len(df)
