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


def test_position_size_capped_by_max_position_pct(monkeypatch):
    from trading_bot.live_runner import _position_size
    from trading_bot.strategies.trend_following import TrendFollowingStrategy

    fake_broker = MagicMock()
    fake_broker.client.fetch_ticker.return_value = {"last": 100.0}
    fake_broker.fetch_balance.return_value = {"total": {"USDT": 10_000.0}}

    strategy = TrendFollowingStrategy()
    strategy.params.stop_loss_pct = 0.001  # tiny stop -> risk sizing would want a huge position

    size = _position_size(
        fake_broker, "BTC/USDT", strategy,
        risk_per_trade_pct=0.01, max_position_pct=0.20, paper=True,
    )

    # Without the cap: risk_amount=100, stop_distance=0.1 -> size=1000 (notional 100,000)
    # With the cap: notional must not exceed 20% of 10,000 = 2,000 -> size <= 20
    assert size * 100.0 <= 10_000.0 * 0.20 + 1e-6


def test_run_live_multi_shares_portfolio_budget_across_symbols(tmp_path, monkeypatch):
    from trading_bot.live_runner import run_live_multi

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("CRYPTO_EXCHANGE", "coinbase")
    monkeypatch.setenv("MAX_ORDER_SIZE", "100000")

    fake_broker = MagicMock()
    fake_broker.client.fetch_ticker.return_value = {"last": 100.0}
    fake_broker.fetch_balance.return_value = {"total": {"USD": 10_000.0}}
    fake_broker.place_order.return_value = {"status": "filled_dryrun"}

    df_up = make_df(trend_up=True)

    with patch("trading_bot.live_runner.CcxtBroker", return_value=fake_broker), \
         patch("trading_bot.live_runner.fetch_ohlcv", return_value=df_up), \
         patch("trading_bot.live_runner.time.sleep"):
        run_live_multi(
            pairs=[("trend_following", "ADA/USD"), ("trend_following", "SOL/USD")],
            timeframe="1h",
            poll_seconds=0,
            risk_per_trade_pct=0.5,  # deliberately huge so the portfolio cap, not risk sizing, binds
            max_portfolio_pct=0.20,
            max_iterations=1,
        )

    # Combined notional placed across both symbols must not exceed 20% of equity (2,000),
    # even though each symbol's own risk-based sizing would have wanted far more.
    total_notional = sum(
        call.args[2] * 100.0 for call in fake_broker.place_order.call_args_list
    )
    assert total_notional <= 10_000.0 * 0.20 + 1e-6
    assert fake_broker.place_order.call_count == 2


def test_run_live_closes_position_at_stop_loss(tmp_path, monkeypatch):
    import json

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("CRYPTO_EXCHANGE", "coinbase")
    monkeypatch.setenv("MAX_ORDER_SIZE", "1000")

    # Open short at 100 with default stop_loss_pct=0.02; price now 103 -> -3% on the short.
    state_file = tmp_path / "live_runner_state_trend_following_ETH_USD.json"
    state_file.write_text(json.dumps(
        {"position": -1, "notional": 100.0, "entry_price": 100.0, "size": 1.0}
    ))

    fake_broker = MagicMock()
    fake_broker.client.fetch_ticker.return_value = {"last": 103.0}
    fake_broker.fetch_balance.return_value = {"total": {"USD": 10_000.0}}
    fake_broker.place_order.return_value = {"status": "filled_dryrun"}

    with patch("trading_bot.live_runner.CcxtBroker", return_value=fake_broker), \
         patch("trading_bot.live_runner.fetch_ohlcv", return_value=make_df(trend_up=False)), \
         patch("trading_bot.live_runner.time.sleep"):
        run_live(
            strategy_name="trend_following",
            symbol="ETH/USD",
            timeframe="1h",
            poll_seconds=0,
            risk_per_trade_pct=0.01,
            max_iterations=1,
        )

    # The stop-loss must buy back exactly the open size and flatten the state.
    fake_broker.place_order.assert_called_once_with("ETH/USD", "buy", 1.0)
    saved = json.loads(state_file.read_text())
    assert saved["position"] == 0
    assert saved["size"] == 0.0
    assert saved["entry_price"] == 0.0


def test_run_live_closes_position_at_take_profit(tmp_path, monkeypatch):
    import json

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("CRYPTO_EXCHANGE", "coinbase")
    monkeypatch.setenv("MAX_ORDER_SIZE", "1000")

    # Open long at 100 with default take_profit_pct=0.06; price now 107 -> +7%.
    state_file = tmp_path / "live_runner_state_trend_following_ETH_USD.json"
    state_file.write_text(json.dumps(
        {"position": 1, "notional": 100.0, "entry_price": 100.0, "size": 1.0}
    ))

    fake_broker = MagicMock()
    fake_broker.client.fetch_ticker.return_value = {"last": 107.0}
    fake_broker.fetch_balance.return_value = {"total": {"USD": 10_000.0}}
    fake_broker.place_order.return_value = {"status": "filled_dryrun"}

    with patch("trading_bot.live_runner.CcxtBroker", return_value=fake_broker), \
         patch("trading_bot.live_runner.fetch_ohlcv", return_value=make_df(trend_up=True)), \
         patch("trading_bot.live_runner.time.sleep"):
        run_live(
            strategy_name="trend_following",
            symbol="ETH/USD",
            timeframe="1h",
            poll_seconds=0,
            risk_per_trade_pct=0.01,
            max_iterations=1,
        )

    fake_broker.place_order.assert_called_once_with("ETH/USD", "sell", 1.0)
    saved = json.loads(state_file.read_text())
    assert saved["position"] == 0


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
