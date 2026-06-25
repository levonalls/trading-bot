from unittest.mock import MagicMock, patch

from trading_bot.data.fetch import fetch_ohlcv


def make_candles(start_ms, count, step_ms):
    return [[start_ms + i * step_ms, 1.0, 1.0, 1.0, 1.0, 1.0] for i in range(count)]


def test_fetch_ohlcv_paginates_when_exchange_caps_batch_size():
    step_ms = 3_600_000  # 1h
    limit = 700
    fake_client = MagicMock()
    fake_client.parse_timeframe.return_value = 3600
    now_ms = 10_000 * step_ms
    fake_client.milliseconds.return_value = now_ms
    start_since = now_ms - step_ms * limit

    def fake_fetch_ohlcv(symbol, timeframe=None, since=None, limit=None):
        batch_size = min(300, limit)
        count = (now_ms - since) // step_ms
        count = max(0, min(batch_size, count))
        if count == 0:
            return []
        return make_candles(since, count, step_ms)

    fake_client.fetch_ohlcv.side_effect = fake_fetch_ohlcv

    with patch("ccxt.coinbase", return_value=fake_client):
        df = fetch_ohlcv("BTC/USD", timeframe="1h", limit=limit, exchange="coinbase")

    assert len(df) == limit
