from __future__ import annotations

import os

from trading_bot.execution.broker_base import Broker

# Live orders require this env var to be set to exactly this value, as a
# deliberate speed bump against accidentally routing real money orders.
LIVE_CONFIRM_VALUE = "I_UNDERSTAND_LIVE_TRADING"


class CcxtBroker(Broker):
    """Crypto spot/futures execution via ccxt.

    Defaults to an exchange's sandbox/testnet ("paper" mode). To place real
    orders you must pass paper=False *and* have
    TRADING_BOT_LIVE_CONFIRM=I_UNDERSTAND_LIVE_TRADING set in the
    environment — this is intentional friction, not a bug.
    """

    def __init__(
        self,
        exchange_id: str = "binance",
        market_type: str = "spot",  # "spot" or "future"
        api_key: str | None = None,
        api_secret: str | None = None,
        paper: bool = True,
    ):
        import ccxt

        self.exchange_id = exchange_id
        self.paper = paper

        env_prefix = exchange_id.upper()
        api_key = api_key or os.environ.get(f"{env_prefix}_API_KEY")
        api_secret = api_secret or os.environ.get(f"{env_prefix}_API_SECRET")

        if not paper and os.environ.get("TRADING_BOT_LIVE_CONFIRM") != LIVE_CONFIRM_VALUE:
            raise RuntimeError(
                "Refusing to start a live CcxtBroker without "
                f"TRADING_BOT_LIVE_CONFIRM={LIVE_CONFIRM_VALUE} set in the environment."
            )

        exchange_class = getattr(ccxt, exchange_id)
        self.client = exchange_class(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "options": {"defaultType": market_type},
                "enableRateLimit": True,
            }
        )

        if paper:
            if not self.client.has.get("sandbox", False) and not hasattr(self.client, "set_sandbox_mode"):
                raise RuntimeError(f"{exchange_id} does not support a ccxt sandbox mode")
            self.client.set_sandbox_mode(True)

    def place_order(self, symbol: str, side: str, size: float, order_type: str = "market") -> dict:
        order = self.client.create_order(symbol, order_type, side, size)
        return {
            "symbol": symbol,
            "side": side,
            "size": size,
            "status": "filled_sandbox" if self.paper else "submitted_live",
            "raw": order,
        }

    def fetch_balance(self) -> dict:
        return self.client.fetch_balance()
