import httpx
import pytest

from trading_bot.data.alpaca_data import fetch_stock_bars


def make_bar(ts: str, price: float, volume: int = 1000) -> dict:
    return {"t": ts, "o": price, "h": price + 0.5, "l": price - 0.5, "c": price, "v": volume}


def make_client(pages: list[dict], seen_requests: list) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        page_index = sum(1 for r in seen_requests[:-1])
        return httpx.Response(200, json=pages[page_index])

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def alpaca_keys(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")


def test_fetch_stock_bars_parses_and_localizes():
    pages = [
        {
            "bars": [
                make_bar("2024-01-08T14:30:00Z", 100.0),
                make_bar("2024-01-08T14:35:00Z", 101.0),
            ],
            "next_page_token": None,
        }
    ]
    seen: list = []
    df = fetch_stock_bars("SPY", timeframe="5Min", limit=10, client=make_client(pages, seen))

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert str(df.index.tz) == "America/New_York"
    assert df.index[0].hour == 9 and df.index[0].minute == 30  # 14:30 UTC == 09:30 ET
    assert df["close"].iloc[-1] == 101.0

    request = seen[0]
    assert request.headers["APCA-API-KEY-ID"] == "test-key"
    assert "SPY/bars" in str(request.url)
    assert "feed=iex" in str(request.url)


def test_fetch_stock_bars_paginates():
    pages = [
        {"bars": [make_bar("2024-01-08T14:30:00Z", 100.0)], "next_page_token": "tok123"},
        {"bars": [make_bar("2024-01-08T14:35:00Z", 101.0)], "next_page_token": None},
    ]
    seen: list = []
    df = fetch_stock_bars("SPY", limit=10, client=make_client(pages, seen))

    assert len(df) == 2
    assert len(seen) == 2
    assert "page_token=tok123" in str(seen[1].url)


def test_fetch_stock_bars_requires_credentials(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="ALPACA_API_KEY"):
        fetch_stock_bars("SPY")


def test_fetch_stock_bars_rejects_unknown_timeframe():
    with pytest.raises(ValueError, match="timeframe"):
        fetch_stock_bars("SPY", timeframe="7Min")


def test_fetch_stock_bars_raises_on_empty_result():
    pages = [{"bars": [], "next_page_token": None}]
    with pytest.raises(RuntimeError, match="no bars"):
        fetch_stock_bars("SPY", client=make_client(pages, []))
