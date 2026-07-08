from __future__ import annotations

import os
from datetime import date
from functools import lru_cache

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from trading_bot.execution.broker_base import Broker
from trading_bot.execution.risk import RiskGuard
from trading_bot.journal.journal import Journal, JournalEntry

app = FastAPI(title="TradingView Webhook Receiver")

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")  # set this; unset means auth is disabled (dev only)
TRADING_MODE = os.environ.get("TRADING_MODE", "paper")  # "paper" or "live"
CRYPTO_EXCHANGE = os.environ.get("CRYPTO_EXCHANGE", "binance")  # ccxt exchange id, e.g. "coinbase"

risk_guard = RiskGuard(
    max_order_size=float(os.environ.get("MAX_ORDER_SIZE", "1.0")),
    max_daily_orders=int(os.environ.get("MAX_DAILY_ORDERS", "50")),
)
journal = Journal()


class TradingViewAlert(BaseModel):
    action: str  # "long" | "short" | "close"
    symbol: str
    size: float = 1.0
    market: str = "crypto"  # "crypto" | "futures" | "stocks" -> ccxt, IB, or Alpaca


@lru_cache(maxsize=3)
def _get_broker(market: str) -> Broker:
    """Lazily construct the broker on first use so importing this module
    (e.g. for tests) never requires exchange/IB credentials or a running
    TWS/IB Gateway instance.
    """
    paper = TRADING_MODE != "live"
    if market == "futures":
        from trading_bot.execution.ib_broker import IBBroker

        return IBBroker(paper=paper)
    if market == "crypto":
        from trading_bot.execution.ccxt_broker import CcxtBroker

        return CcxtBroker(exchange_id=CRYPTO_EXCHANGE, paper=paper)
    if market == "stocks":
        from trading_bot.execution.alpaca_broker import AlpacaBroker

        return AlpacaBroker(paper=paper)
    raise ValueError(f"Unknown market '{market}'")


def _check_auth(x_webhook_secret: str | None) -> None:
    if WEBHOOK_SECRET and x_webhook_secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="invalid webhook secret")


@app.post("/webhook")
def receive_alert(alert: TradingViewAlert, x_webhook_secret: str | None = Header(default=None)) -> dict:
    """Receives `alertcondition` payloads from the Pine scripts in
    trading_bot/pinescript/templates and routes them to a broker, subject
    to the risk guard. Set the TradingView alert's webhook URL to this
    endpoint's `/webhook` path and its "Webhook URL" headers to include
    `x-webhook-secret: <WEBHOOK_SECRET>`.
    """
    _check_auth(x_webhook_secret)

    if alert.action == "close":
        return _close_position(alert)

    side = {"long": "buy", "short": "sell"}.get(alert.action)
    if side is None:
        return {"status": "ignored", "alert": alert.model_dump()}

    allowed, reason = risk_guard.check(alert.size)
    if not allowed:
        journal.log(
            JournalEntry(
                entry_date=date.today().isoformat(),
                strategy="webhook",
                symbol=alert.symbol,
                metrics={"rejected": True},
                notes=f"order rejected by risk guard: {reason}",
            )
        )
        raise HTTPException(status_code=429, detail=f"order rejected: {reason}")

    broker = _get_broker(alert.market)
    order = broker.place_order(alert.symbol, side, alert.size)
    risk_guard.record_order()

    journal.log(
        JournalEntry(
            entry_date=date.today().isoformat(),
            strategy="webhook",
            symbol=alert.symbol,
            metrics={"side": side, "size": alert.size, "mode": TRADING_MODE},
            notes=f"order placed via {alert.market} broker: {order}",
        )
    )
    return {"status": "ok", "order": order}


def _close_position(alert: TradingViewAlert) -> dict:
    """Close an existing position (used by copy-trade exit signals).

    Closes reduce exposure, so they skip the size cap — but the kill switch
    and daily order cap still apply (size 0 passes the size check only).
    Brokers without close support (ccxt/IB adapters, currently) ignore the
    alert rather than guessing at position state.
    """
    allowed, reason = risk_guard.check(0)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"close rejected: {reason}")

    broker = _get_broker(alert.market)
    if not hasattr(broker, "close_position"):
        return {"status": "ignored", "reason": f"{alert.market} broker has no close support"}

    result = broker.close_position(alert.symbol)
    risk_guard.record_order()
    journal.log(
        JournalEntry(
            entry_date=date.today().isoformat(),
            strategy="webhook",
            symbol=alert.symbol,
            metrics={"action": "close", "mode": TRADING_MODE},
            notes=f"position closed via {alert.market} broker: {result}",
        )
    )
    return {"status": "ok", "order": result}


@app.post("/kill")
def kill_switch(x_webhook_secret: str | None = Header(default=None)) -> dict:
    """Immediately halts all new orders until /rearm is called."""
    _check_auth(x_webhook_secret)
    risk_guard.kill()
    return {"status": "killed"}


@app.post("/rearm")
def rearm(x_webhook_secret: str | None = Header(default=None)) -> dict:
    _check_auth(x_webhook_secret)
    risk_guard.rearm()
    return {"status": "rearmed"}
