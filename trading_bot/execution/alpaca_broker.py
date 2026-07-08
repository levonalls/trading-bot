from __future__ import annotations

import os

from trading_bot.execution.broker_base import Broker
from trading_bot.execution.ccxt_broker import LIVE_CONFIRM_VALUE

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"


class AlpacaBroker(Broker):
    """US equities execution via Alpaca's Trading API.

    paper=True (default) routes every order to Alpaca's paper-trading
    endpoint — a full simulated brokerage, so fills, positions, and P&L are
    all inspectable without risking funds. The same API keys work for both
    the paper endpoint and market data.

    To place real orders you must pass paper=False *and* have
    TRADING_BOT_LIVE_CONFIRM=I_UNDERSTAND_LIVE_TRADING set in the
    environment — the same deliberate speed bump as CcxtBroker/IBBroker.

    Orders default to time_in_force="day" so anything unfilled dies at the
    close, matching the intraday strategies' no-overnight invariant.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        paper: bool = True,
        client=None,
    ):
        import httpx

        self.paper = paper
        api_key = api_key or os.environ.get("ALPACA_API_KEY")
        api_secret = api_secret or os.environ.get("ALPACA_API_SECRET")

        if not paper and os.environ.get("TRADING_BOT_LIVE_CONFIRM") != LIVE_CONFIRM_VALUE:
            raise RuntimeError(
                "Refusing to start a live AlpacaBroker without "
                f"TRADING_BOT_LIVE_CONFIRM={LIVE_CONFIRM_VALUE} set in the environment."
            )

        self.client = client or httpx.Client(
            base_url=PAPER_URL if paper else LIVE_URL,
            headers={"APCA-API-KEY-ID": api_key or "", "APCA-API-SECRET-KEY": api_secret or ""},
            timeout=30,
        )

    def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "market",
        time_in_force: str = "day",
    ) -> dict:
        resp = self.client.post(
            "/v2/orders",
            json={
                "symbol": symbol,
                "side": side,
                "qty": str(size),
                "type": order_type,
                "time_in_force": time_in_force,
            },
        )
        resp.raise_for_status()
        return {
            "symbol": symbol,
            "side": side,
            "size": size,
            "status": "submitted_paper" if self.paper else "submitted_live",
            "raw": resp.json(),
        }

    def fetch_balance(self) -> dict:
        resp = self.client.get("/v2/account")
        resp.raise_for_status()
        return resp.json()
