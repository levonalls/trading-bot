import importlib
from unittest.mock import patch


def test_get_broker_uses_configured_crypto_exchange(monkeypatch):
    monkeypatch.setenv("CRYPTO_EXCHANGE", "coinbase")
    monkeypatch.delenv("TRADING_MODE", raising=False)

    import trading_bot.webhook_server as webhook_server

    importlib.reload(webhook_server)
    webhook_server._get_broker.cache_clear()

    with patch("trading_bot.execution.ccxt_broker.CcxtBroker") as MockBroker:
        webhook_server._get_broker("crypto")
        MockBroker.assert_called_once_with(exchange_id="coinbase", paper=True)
