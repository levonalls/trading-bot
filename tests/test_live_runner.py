import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from trading_bot.live_runner import run_live


def make_df(n=300, trend_up=True):
    idx = pd.date_range("2023-01-01", periods=n, freq="h")
    drift = np.linspace(0, 50 if trend_up else -50, n)
    close = 100 + drift
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}, index=idx
    )


def test_run_live_places_one_order_then_holds(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("CRYPTO_EXCHANGE", "binance")
    monkeypatch.setenv("MAX_ORDER_SIZE", "1000")

    fake_broker = MagicMock()
    fake_broker.client.fetch_ticker.return_value = {"last": 100.0}
    fake_broker.fetch_balance.return_value = {"total": {"USDT": 10_000.0}}
    fake_broker.place_order.return_value = {"status": "filled_sandbox"}

    df = make_df(trend_up=True)

    with patch("trading_bot.live_runner.CcxtBroker", return_value=fake_broker), \
         patch("trading_bot.live_runner.fetch_ohlcv", return_value=df), \
         patch("trading_bot.live_runner.time.sleep"):
        run_live(
            strategy_name="trend_following",
            symbol="BTC/USDT",
            timeframe="1h",
            poll_seconds=0,
            risk_per_trade_pct=0.01,
            max_iterations=3,
        )

    # Same signal every iteration -> only the first iteration should place an order
    assert fake_broker.place_order.call_count == 1

    state_file = tmp_path / "live_runner_state_trend_following_BTC_USDT.json"
    assert state_file.exists()


def test_run_live_respects_kill_switch_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRADING_MODE", "paper")
    kill_file = tmp_path / "live_runner.kill"
    kill_file.write_text("stop")
    monkeypatch.setenv("LIVE_RUNNER_KILL_FILE", str(kill_file))

    import trading_bot.live_runner as live_runner

    fake_broker = MagicMock()
    with patch("trading_bot.live_runner.CcxtBroker", return_value=fake_broker), \
         patch("trading_bot.live_runner.KILL_SWITCH_FILE", kill_file):
        live_runner.run_live(
            strategy_name="trend_following",
            symbol="BTC/USDT",
            timeframe="1h",
            poll_seconds=0,
            risk_per_trade_pct=0.01,
            max_iterations=5,
        )

    fake_broker.place_order.assert_not_called()
