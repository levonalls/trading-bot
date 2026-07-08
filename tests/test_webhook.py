import importlib
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient


def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret")
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.chdir(tmp_path)

    import trading_bot.webhook_server as webhook_server

    importlib.reload(webhook_server)
    webhook_server._get_broker.cache_clear()

    from trading_bot.execution.broker_base import PaperBroker

    fake_broker = PaperBroker()
    webhook_server._get_broker.cache_clear()
    monkeypatch.setattr(webhook_server, "_get_broker", lambda market: fake_broker)

    return TestClient(webhook_server.app), webhook_server, fake_broker


def test_webhook_rejects_without_secret(monkeypatch, tmp_path):
    client, _, _ = make_client(monkeypatch, tmp_path)
    resp = client.post("/webhook", json={"action": "long", "symbol": "BTC/USDT", "size": 0.1})
    assert resp.status_code == 401


def test_webhook_places_order_with_valid_secret(monkeypatch, tmp_path):
    client, _, fake_broker = make_client(monkeypatch, tmp_path)
    resp = client.post(
        "/webhook",
        json={"action": "long", "symbol": "BTC/USDT", "size": 0.1},
        headers={"x-webhook-secret": "test-secret"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert len(fake_broker.orders) == 1


def test_webhook_rejects_oversized_order(monkeypatch, tmp_path):
    client, webhook_server, _ = make_client(monkeypatch, tmp_path)
    webhook_server.risk_guard.max_order_size = 0.05
    resp = client.post(
        "/webhook",
        json={"action": "long", "symbol": "BTC/USDT", "size": 1.0},
        headers={"x-webhook-secret": "test-secret"},
    )
    assert resp.status_code == 429


def test_webhook_routes_close_to_broker(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    client, webhook_server, _ = make_client(monkeypatch, tmp_path)
    stock_broker = MagicMock()
    stock_broker.close_position.return_value = {"symbol": "AAPL", "status": "closed_paper"}
    monkeypatch.setattr(webhook_server, "_get_broker", lambda market: stock_broker)

    resp = client.post(
        "/webhook",
        json={"action": "close", "symbol": "AAPL", "market": "stocks"},
        headers={"x-webhook-secret": "test-secret"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    stock_broker.close_position.assert_called_once_with("AAPL")


def test_webhook_close_ignored_for_brokers_without_close_support(monkeypatch, tmp_path):
    client, _, fake_broker = make_client(monkeypatch, tmp_path)  # PaperBroker: no close_position
    resp = client.post(
        "/webhook",
        json={"action": "close", "symbol": "BTC/USDT"},
        headers={"x-webhook-secret": "test-secret"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    assert fake_broker.orders == []


def test_kill_switch_blocks_subsequent_orders(monkeypatch, tmp_path):
    client, _, _ = make_client(monkeypatch, tmp_path)
    headers = {"x-webhook-secret": "test-secret"}
    assert client.post("/kill", headers=headers).status_code == 200

    resp = client.post(
        "/webhook",
        json={"action": "long", "symbol": "BTC/USDT", "size": 0.1},
        headers=headers,
    )
    assert resp.status_code == 429

    assert client.post("/rearm", headers=headers).status_code == 200
    resp = client.post(
        "/webhook",
        json={"action": "long", "symbol": "BTC/USDT", "size": 0.1},
        headers=headers,
    )
    assert resp.status_code == 200
