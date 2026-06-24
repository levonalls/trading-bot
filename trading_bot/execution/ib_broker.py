from __future__ import annotations

import os

from trading_bot.execution.broker_base import Broker
from trading_bot.execution.ccxt_broker import LIVE_CONFIRM_VALUE

PAPER_PORT = 7497  # TWS paper trading default
LIVE_PORT = 7496  # TWS live trading default


class IBBroker(Broker):
    """Futures (and other IB-listed instrument) execution via Interactive
    Brokers, through ib_insync.

    Requires TWS or IB Gateway running and logged in to either a paper or
    live account — the port you connect to is what actually determines
    paper vs. live, IB has no separate "sandbox" flag. As with CcxtBroker,
    live trading additionally requires
    TRADING_BOT_LIVE_CONFIRM=I_UNDERSTAND_LIVE_TRADING.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int | None = None,
        client_id: int = 1,
        paper: bool = True,
    ):
        from ib_insync import IB

        self.paper = paper
        port = port or (PAPER_PORT if paper else LIVE_PORT)

        if not paper and os.environ.get("TRADING_BOT_LIVE_CONFIRM") != LIVE_CONFIRM_VALUE:
            raise RuntimeError(
                "Refusing to start a live IBBroker without "
                f"TRADING_BOT_LIVE_CONFIRM={LIVE_CONFIRM_VALUE} set in the environment."
            )

        self.ib = IB()
        self.ib.connect(host, port, clientId=client_id)

    def place_order(self, symbol: str, side: str, size: float, sec_type: str = "FUT") -> dict:
        from ib_insync import Future, MarketOrder, Stock

        contract = Future(symbol) if sec_type == "FUT" else Stock(symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)

        order = MarketOrder("BUY" if side == "buy" else "SELL", size)
        trade = self.ib.placeOrder(contract, order)
        self.ib.sleep(1)

        return {
            "symbol": symbol,
            "side": side,
            "size": size,
            "status": "submitted_paper" if self.paper else "submitted_live",
            "order_status": trade.orderStatus.status,
        }

    def disconnect(self) -> None:
        self.ib.disconnect()
