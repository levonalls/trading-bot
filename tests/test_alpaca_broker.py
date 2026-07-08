import httpx
import pytest

from trading_bot.execution.alpaca_broker import LIVE_URL, PAPER_URL, AlpacaBroker


def make_client(base_url: str, seen_requests: list, response_json: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json=response_json)

    return httpx.Client(base_url=base_url, transport=httpx.MockTransport(handler))


def test_paper_order_uses_day_time_in_force():
    seen: list = []
    client = make_client(PAPER_URL, seen, {"id": "order-1", "status": "accepted"})
    broker = AlpacaBroker(api_key="k", api_secret="s", paper=True, client=client)

    order = broker.place_order("AAPL", "buy", 10)

    assert order["status"] == "submitted_paper"
    assert order["raw"]["id"] == "order-1"
    import json

    body = json.loads(seen[0].content)
    assert body == {"symbol": "AAPL", "side": "buy", "qty": "10", "type": "market", "time_in_force": "day"}
    assert str(seen[0].url).startswith(PAPER_URL)


def test_live_requires_confirm_env_var(monkeypatch):
    monkeypatch.delenv("TRADING_BOT_LIVE_CONFIRM", raising=False)
    with pytest.raises(RuntimeError, match="TRADING_BOT_LIVE_CONFIRM"):
        AlpacaBroker(api_key="k", api_secret="s", paper=False)


def test_live_allowed_with_confirm(monkeypatch):
    monkeypatch.setenv("TRADING_BOT_LIVE_CONFIRM", "I_UNDERSTAND_LIVE_TRADING")
    seen: list = []
    client = make_client(LIVE_URL, seen, {"id": "order-2"})
    broker = AlpacaBroker(api_key="k", api_secret="s", paper=False, client=client)

    order = broker.place_order("AAPL", "sell", 5)
    assert order["status"] == "submitted_live"


def test_fetch_balance_hits_account_endpoint():
    seen: list = []
    client = make_client(PAPER_URL, seen, {"equity": "100000", "buying_power": "200000"})
    broker = AlpacaBroker(api_key="k", api_secret="s", paper=True, client=client)

    balance = broker.fetch_balance()
    assert balance["equity"] == "100000"
    assert str(seen[0].url).endswith("/v2/account")
