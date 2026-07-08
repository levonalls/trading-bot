import json

import httpx
import pytest

from trading_bot.copytrade.collective2 import Collective2Client, LeaderSignal
from trading_bot.copytrade.monitor import CopyTradeMonitor, MonitorConfig, size_from_risk


def c2_response(signals: list[dict]) -> dict:
    return {"ok": 1, "response": signals}


def make_c2_client(payloads: list[dict]) -> Collective2Client:
    calls = iter(payloads)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["apikey"] == "c2-key"
        return httpx.Response(200, json=next(calls))

    return Collective2Client(api_key="c2-key", client=httpx.Client(transport=httpx.MockTransport(handler)))


def make_monitor(tmp_path, c2_client, webhook_status=200, equity=100.0):
    webhook_calls: list[dict] = []

    def webhook_handler(request: httpx.Request) -> httpx.Response:
        webhook_calls.append(json.loads(request.content))
        return httpx.Response(webhook_status, json={"status": "ok"})

    config = MonitorConfig(
        strategy_ids=["9001"],
        webhook_secret="test-secret",
        equity=equity,
        risk_per_trade_pct=0.10,
        stop_loss_pct=0.06,
        max_position_pct=1.0,
        state_path=str(tmp_path / "state.json"),
        kill_file=str(tmp_path / "copytrade.kill"),
    )
    monitor = CopyTradeMonitor(
        config,
        c2_client=c2_client,
        http_client=httpx.Client(transport=httpx.MockTransport(webhook_handler)),
        price_fn=lambda symbol: 50.0,
    )
    return monitor, webhook_calls


# ---- Collective2 client ----


def test_c2_client_parses_signals():
    client = make_c2_client(
        [c2_response([{"signal_id": "111", "symbol": "AAPL", "action": "BTO", "quant": "10", "limit": "150.5"}])]
    )
    signals = client.fetch_signals("9001")

    assert len(signals) == 1
    s = signals[0]
    assert s.signal_id == "111"
    assert s.symbol == "AAPL"
    assert s.webhook_action() == "long"
    assert s.limit_price == 150.5


def test_c2_client_raises_on_api_error():
    client = make_c2_client([{"ok": 0, "error": "bad apikey"}])
    with pytest.raises(RuntimeError, match="bad apikey"):
        client.fetch_signals("9001")


def test_c2_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("C2_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="C2_API_KEY"):
        Collective2Client()


def test_action_mapping():
    assert LeaderSignal("1", "9", "X", "BTO").webhook_action() == "long"
    assert LeaderSignal("1", "9", "X", "SSHORT").webhook_action() == "short"
    assert LeaderSignal("1", "9", "X", "STC").webhook_action() == "close"
    assert LeaderSignal("1", "9", "X", "BTC").webhook_action() == "close"
    assert LeaderSignal("1", "9", "X", "WEIRD").webhook_action() is None


# ---- sizing ----


def test_size_from_risk_uses_stop_distance():
    # $100 equity, 10% risk = $10; $50 stock with 6% stop risks $3/share
    # -> 3.33 shares, but capped at $100 notional = 2 shares.
    assert size_from_risk(100, 50, 0.10, 0.06, max_position_pct=1.0) == 2.0


def test_size_from_risk_cap_binds():
    # Without the cap this would be 33.3 shares ($1,666 notional on $100).
    uncapped = (100 * 0.10) / (5 * 0.06)
    assert uncapped > 20
    assert size_from_risk(100, 5, 0.10, 0.06, max_position_pct=1.0) == 20.0


def test_size_from_risk_zero_on_bad_price():
    assert size_from_risk(100, 0, 0.10, 0.06, 1.0) == 0.0


# ---- monitor ----


def test_monitor_relays_and_sizes_by_own_rules(tmp_path):
    # Leader trades 500 shares; we must ignore that and size from our risk.
    c2 = make_c2_client(
        [c2_response([{"signal_id": "111", "symbol": "AAPL", "action": "BTO", "quant": "500"}])]
    )
    monitor, webhook_calls = make_monitor(tmp_path, c2)

    relayed = monitor.poll_once()

    assert len(relayed) == 1
    assert webhook_calls == [{"action": "long", "symbol": "AAPL", "size": 2.0, "market": "stocks"}]


def test_monitor_dedupes_across_polls_and_restarts(tmp_path):
    same_signal = c2_response([{"signal_id": "111", "symbol": "AAPL", "action": "BTO"}])
    c2 = make_c2_client([same_signal, same_signal])
    monitor, webhook_calls = make_monitor(tmp_path, c2)

    monitor.poll_once()
    monitor.poll_once()
    assert len(webhook_calls) == 1

    # A fresh monitor with the same state file must not re-fire either.
    c2_again = make_c2_client([same_signal])
    monitor2, webhook_calls2 = make_monitor(tmp_path, c2_again)
    monitor2.poll_once()
    assert webhook_calls2 == []


def test_monitor_relays_close_without_sizing(tmp_path):
    c2 = make_c2_client([c2_response([{"signal_id": "222", "symbol": "AAPL", "action": "STC"}])])
    monitor, webhook_calls = make_monitor(tmp_path, c2)

    monitor.poll_once()
    assert webhook_calls == [{"action": "close", "symbol": "AAPL", "size": 0.0, "market": "stocks"}]


def test_monitor_marks_risk_guard_rejections_as_final(tmp_path):
    signal = c2_response([{"signal_id": "333", "symbol": "AAPL", "action": "BTO"}])
    c2 = make_c2_client([signal, signal])
    monitor, webhook_calls = make_monitor(tmp_path, c2, webhook_status=429)

    monitor.poll_once()
    monitor.poll_once()
    # Rejected by the risk guard once; never re-fired.
    assert len(webhook_calls) == 1


def test_monitor_retries_when_price_unavailable(tmp_path):
    signal = c2_response([{"signal_id": "444", "symbol": "AAPL", "action": "BTO"}])
    c2 = make_c2_client([signal, signal])
    monitor, webhook_calls = make_monitor(tmp_path, c2)

    def flaky_price(symbol):
        raise RuntimeError("quote feed down")

    monitor.price_fn = flaky_price
    monitor.poll_once()
    assert webhook_calls == []
    assert "444" not in monitor.seen  # left unseen so the next poll retries

    monitor.price_fn = lambda symbol: 50.0
    monitor.poll_once()
    assert len(webhook_calls) == 1
