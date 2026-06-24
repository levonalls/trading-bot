from unittest.mock import MagicMock, patch

from trading_bot.execution.ccxt_broker import CcxtBroker


def test_paper_mode_falls_back_to_dry_run_when_no_sandbox():
    fake_client = MagicMock()
    fake_client.has = {"sandbox": False}
    fake_client.urls = {}
    fake_client.fetch_ticker.return_value = {"last": 65000.0}

    with patch("ccxt.coinbase", return_value=fake_client):
        broker = CcxtBroker(exchange_id="coinbase", paper=True)

    assert broker.dry_run is True
    order = broker.place_order("BTC/USD", "buy", 0.01)
    assert order["status"] == "filled_dryrun"
    assert order["simulated_price"] == 65000.0
    fake_client.create_order.assert_not_called()


def test_paper_mode_uses_real_sandbox_when_available():
    fake_client = MagicMock()
    fake_client.has = {"sandbox": True}
    fake_client.urls = {"test": "https://testnet.example.com"}
    fake_client.create_order.return_value = {"id": "123"}

    with patch("ccxt.binance", return_value=fake_client):
        broker = CcxtBroker(exchange_id="binance", paper=True)

    assert broker.dry_run is False
    fake_client.set_sandbox_mode.assert_called_once_with(True)
    order = broker.place_order("BTC/USDT", "buy", 0.01)
    assert order["status"] == "filled_sandbox"
    fake_client.create_order.assert_called_once()


def test_live_requires_confirm_env_var(monkeypatch):
    monkeypatch.delenv("TRADING_BOT_LIVE_CONFIRM", raising=False)
    try:
        CcxtBroker(exchange_id="coinbase", paper=False)
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "TRADING_BOT_LIVE_CONFIRM" in str(e)
