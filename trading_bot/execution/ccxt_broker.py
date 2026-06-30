from __future__ import annotations

import os

from trading_bot.execution.broker_base import Broker

# Live orders require this env var to be set to exactly this value, as a
# deliberate speed bump against accidentally routing real money orders.
LIVE_CONFIRM_VALUE = "I_UNDERSTAND_LIVE_TRADING"


def _has_sandbox(client) -> bool:
    """Whether this ccxt exchange has a real test/sandbox endpoint.

    Some exchanges (e.g. Coinbase's Advanced Trade API) have no sandbox at
    all — calling set_sandbox_mode(True) on them raises, since ccxt has no
    test URL to swap in. has['sandbox'] is the authoritative flag; checking
    urls['test'] as a fallback covers older ccxt versions that don't set it.
    """
    return bool(client.has.get("sandbox")) or bool(client.urls.get("test"))


class CcxtBroker(Broker):
    """Crypto spot/futures execution via ccxt.

    paper=True (default) never risks real funds:
    - On exchanges with a real sandbox/testnet (e.g. Binance), orders are
      sent to that sandbox using sandbox API keys.
    - On exchanges with no sandbox (e.g. Coinbase), orders are simulated
      locally against the real, live market price (fetched read-only) and
      never submitted — "status": "filled_dryrun" makes this explicit.

    To place real orders you must pass paper=False *and* have
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
                # Some exchanges (e.g. Coinbase) otherwise require a `price` arg
                # on market buy orders just to compute cost = amount * price.
                # We always size in base-currency units, so tell ccxt not to
                # demand that -- the exchange fills at the live market price.
                "options": {"defaultType": market_type, "createMarketBuyOrderRequiresPrice": False},
                "enableRateLimit": True,
            }
        )

        self.dry_run = False
        if paper:
            if _has_sandbox(self.client):
                self.client.set_sandbox_mode(True)
            else:
                self.dry_run = True

    def place_order(self, symbol: str, side: str, size: float, order_type: str = "market") -> dict:
        if self.dry_run:
            ticker = self.client.fetch_ticker(symbol)
            return {
                "symbol": symbol,
                "side": side,
                "size": size,
                "status": "filled_dryrun",
                "simulated_price": ticker["last"],
            }

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
