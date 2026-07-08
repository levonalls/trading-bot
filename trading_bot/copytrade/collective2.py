from __future__ import annotations

import os
from dataclasses import dataclass

# Collective2's JSON API. The v3 "world" API is the documented public
# surface; C2 also has a newer v4 — if your account is on v4, point
# C2_API_BASE at it and adjust the endpoint below.
DEFAULT_API_BASE = "https://api.collective2.com/world/apiv3"


@dataclass
class LeaderSignal:
    """One trade signal published by a Collective2 strategy ("leader")."""

    signal_id: str
    strategy_id: str
    symbol: str
    action: str  # C2 actions: BTO, STC, SSHORT, BTC
    quantity: float | None = None
    limit_price: float | None = None
    posted_at: str | None = None

    # How a leader's C2 action translates into our webhook's action.
    # BTO opens long, SSHORT opens short; STC/BTC close existing positions.
    _ACTION_MAP = {"BTO": "long", "SSHORT": "short", "STC": "close", "BTC": "close"}

    def webhook_action(self) -> str | None:
        return self._ACTION_MAP.get(self.action.upper())


class Collective2Client:
    """Minimal read-only client for a Collective2 strategy's signals.

    Requires a C2 API key (env C2_API_KEY) and an active subscription to
    each strategy you want to follow — C2 only returns signals for
    strategies your account is entitled to.
    """

    def __init__(self, api_key: str | None = None, api_base: str | None = None, client=None):
        import httpx

        self.api_key = api_key or os.environ.get("C2_API_KEY")
        if not self.api_key:
            raise RuntimeError("Collective2 API key missing: set C2_API_KEY.")
        self.api_base = (api_base or os.environ.get("C2_API_BASE") or DEFAULT_API_BASE).rstrip("/")
        self.client = client or httpx.Client(timeout=30)

    def fetch_signals(self, strategy_id: str) -> list[LeaderSignal]:
        """Fetch the strategy's current signals (working + recently filled)."""
        resp = self.client.post(
            f"{self.api_base}/retrieveSignalsAll",
            json={"apikey": self.api_key, "systemid": strategy_id},
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("ok") in (0, "0", False):
            raise RuntimeError(f"Collective2 error for strategy {strategy_id}: {payload.get('error', payload)}")

        signals = []
        for raw in payload.get("response") or []:
            signal = self._parse_signal(raw, strategy_id)
            if signal is not None:
                signals.append(signal)
        return signals

    @staticmethod
    def _parse_signal(raw: dict, strategy_id: str) -> LeaderSignal | None:
        signal_id = raw.get("signal_id") or raw.get("signalid")
        symbol = raw.get("symbol")
        action = raw.get("action")
        if not signal_id or not symbol or not action:
            return None

        def num(key: str) -> float | None:
            value = raw.get(key)
            try:
                return float(value) if value not in (None, "", "0", 0) else None
            except (TypeError, ValueError):
                return None

        return LeaderSignal(
            signal_id=str(signal_id),
            strategy_id=str(strategy_id),
            symbol=str(symbol),
            action=str(action),
            quantity=num("quant"),
            limit_price=num("limit"),
            posted_at=raw.get("postedwhen"),
        )
