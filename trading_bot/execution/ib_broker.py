from __future__ import annotations

import os

import pandas as pd

from trading_bot.execution.broker_base import Broker
from trading_bot.execution.ccxt_broker import LIVE_CONFIRM_VALUE

PAPER_PORT = 7497  # TWS paper trading default
LIVE_PORT = 7496  # TWS live trading default

# ib_insync historicalData bar sizes, keyed by the same timeframe strings
# the rest of the bot uses (ccxt-style) so callers don't need to know IB's
# separate "1 hour" / "1 day" naming.
_BAR_SIZES = {
    "1m": "1 min", "5m": "5 mins", "15m": "15 mins", "30m": "30 mins",
    "1h": "1 hour", "4h": "4 hours", "1d": "1 day",
}
_TIMEFRAME_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400,
}


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

    def _qualified_contract(self, symbol: str, sec_type: str = "FUT"):
        from ib_insync import Future, Stock

        contract = Future(symbol) if sec_type == "FUT" else Stock(symbol, "SMART", "USD")
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            raise RuntimeError(f"IB could not qualify contract for '{symbol}'.")
        # IB often returns multiple expiries for a bare symbol — pick the
        # front month (nearest expiry) so the bot always trades the most
        # liquid contract without requiring an explicit expiry date.
        return sorted(qualified, key=lambda c: c.lastTradeDateOrContractMonth)[0]

    def place_order(self, symbol: str, side: str, size: float, sec_type: str = "FUT") -> dict:
        from ib_insync import MarketOrder

        contract = self._qualified_contract(symbol, sec_type)

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

    def contract_multiplier(self, symbol: str, sec_type: str = "FUT") -> float:
        """Points-to-dollars multiplier for the contract (e.g. $5/point for
        MES), needed to size futures in whole contracts rather than the
        fractional 'base units' crypto sizing uses.
        """
        contract = self._qualified_contract(symbol, sec_type)
        return float(contract.multiplier or 1)

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 300, sec_type: str = "FUT") -> pd.DataFrame:
        """Historical bars for `symbol`, shaped like the rest of the bot's
        OHLCV DataFrames (timestamp-indexed, open/high/low/close/volume).
        """
        bar_size = _BAR_SIZES.get(timeframe)
        if bar_size is None:
            raise ValueError(f"Unsupported timeframe '{timeframe}' for IB; supported: {sorted(_BAR_SIZES)}")

        contract = self._qualified_contract(symbol, sec_type)
        duration_days = max(1, -(-(limit * _TIMEFRAME_SECONDS[timeframe]) // 86400))  # ceil division
        bars = self.ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=f"{duration_days} D",
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=False,
            formatDate=1,
        )
        df = pd.DataFrame(
            [{"timestamp": b.date, "open": b.open, "high": b.high, "low": b.low,
              "close": b.close, "volume": b.volume} for b in bars]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df.set_index("timestamp").tail(limit)

    def account_equity(self, tag: str = "NetLiquidation") -> float:
        for row in self.ib.accountSummary():
            if row.tag == tag:
                return float(row.value)
        raise RuntimeError(f"Account summary tag '{tag}' not found.")

    def disconnect(self) -> None:
        self.ib.disconnect()
