from __future__ import annotations

from abc import ABC, abstractmethod


class Broker(ABC):
    """Execution adapter interface. Live trading (Phase 3) implements this
    against ccxt for crypto and a futures broker API; for now only a paper
    broker exists so the webhook path can be exercised end-to-end safely.
    """

    @abstractmethod
    def place_order(self, symbol: str, side: str, size: float) -> dict:
        raise NotImplementedError


class PaperBroker(Broker):
    def __init__(self):
        self.orders: list[dict] = []

    def place_order(self, symbol: str, side: str, size: float) -> dict:
        order = {"symbol": symbol, "side": side, "size": size, "status": "filled_paper"}
        self.orders.append(order)
        return order
