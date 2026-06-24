from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from trading_bot.execution.broker_base import PaperBroker

app = FastAPI(title="TradingView Webhook Receiver")
broker = PaperBroker()


class TradingViewAlert(BaseModel):
    action: str  # "long" | "short" | "close"
    symbol: str
    size: float = 1.0


@app.post("/webhook")
def receive_alert(alert: TradingViewAlert) -> dict:
    """Receives `alertcondition` payloads from the Pine scripts in
    trading_bot/pinescript/templates and routes them to a broker. Paper-only
    until Phase 3 wires in a real ccxt/futures broker.
    """
    side = "buy" if alert.action == "long" else "sell" if alert.action == "short" else None
    if side is None:
        return {"status": "ignored", "alert": alert.model_dump()}

    order = broker.place_order(alert.symbol, side, alert.size)
    return {"status": "ok", "order": order}
