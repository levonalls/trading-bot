from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from trading_bot.copytrade.collective2 import Collective2Client, LeaderSignal


@dataclass
class MonitorConfig:
    strategy_ids: list[str]
    webhook_url: str = "http://127.0.0.1:8000/webhook"
    webhook_secret: str | None = field(default_factory=lambda: os.environ.get("WEBHOOK_SECRET"))
    equity: float = 100.0
    risk_per_trade_pct: float = 0.10
    stop_loss_pct: float = 0.06
    max_position_pct: float = 1.0
    poll_seconds: int = 300
    state_path: str = "copytrade_state.json"
    kill_file: str = "copytrade.kill"


def size_from_risk(equity: float, price: float, risk_pct: float, stop_pct: float, max_position_pct: float) -> float:
    """Shares to buy so a stop-loss hit risks `risk_pct` of equity, capped so
    total notional never exceeds `max_position_pct` of equity.

    This is the core copy-trading safety property: we mirror the leader's
    *direction*, never their size or leverage — their account is not ours.
    """
    if price <= 0 or stop_pct <= 0:
        return 0.0
    shares = (equity * risk_pct) / (price * stop_pct)
    max_shares = (equity * max_position_pct) / price
    return round(min(shares, max_shares), 4)


class CopyTradeMonitor:
    """Polls Collective2 strategies and relays new signals to the webhook
    server, which owns execution, the kill switch, and the order caps.

    Every relayed order is re-sized by OUR risk rules (see size_from_risk).
    Signal IDs already relayed are persisted to `state_path` so a restart
    never re-fires an old trade — same pattern as live_runner.
    """

    def __init__(self, config: MonitorConfig, c2_client: Collective2Client | None = None, http_client=None, price_fn=None):
        import httpx

        self.config = config
        self.c2 = c2_client or Collective2Client()
        self.http = http_client or httpx.Client(timeout=30)
        self.price_fn = price_fn or self._last_close
        self.seen: set[str] = self._load_state()

    # ---- state ----

    def _load_state(self) -> set[str]:
        path = Path(self.config.state_path)
        if path.exists():
            return set(json.loads(path.read_text()).get("seen_signal_ids", []))
        return set()

    def _save_state(self) -> None:
        Path(self.config.state_path).write_text(json.dumps({"seen_signal_ids": sorted(self.seen)}))

    # ---- pricing ----

    @staticmethod
    def _last_close(symbol: str) -> float:
        from trading_bot.data.alpaca_data import fetch_stock_bars

        return float(fetch_stock_bars(symbol, timeframe="1Day", limit=1)["close"].iloc[-1])

    # ---- polling ----

    def poll_once(self) -> list[dict]:
        """One polling pass over all followed strategies; returns the webhook
        responses for every signal relayed this pass."""
        relayed = []
        for strategy_id in self.config.strategy_ids:
            try:
                signals = self.c2.fetch_signals(strategy_id)
            except Exception as exc:
                print(f"[copytrade] failed to fetch strategy {strategy_id}: {exc}")
                continue
            for signal in signals:
                if signal.signal_id in self.seen:
                    continue
                result = self._relay(signal)
                if result is not None:
                    relayed.append(result)
        self._save_state()
        return relayed

    def _relay(self, signal: LeaderSignal) -> dict | None:
        action = signal.webhook_action()
        if action is None:
            print(f"[copytrade] {signal.symbol}: unsupported action {signal.action!r}, skipping")
            self.seen.add(signal.signal_id)
            return None

        size = 0.0
        if action in ("long", "short"):
            try:
                price = signal.limit_price or self.price_fn(signal.symbol)
            except Exception as exc:
                # No price -> can't size safely. Leave unseen so the next
                # poll retries once quotes are available again.
                print(f"[copytrade] {signal.symbol}: no price available ({exc}), will retry")
                return None
            size = size_from_risk(
                self.config.equity,
                price,
                self.config.risk_per_trade_pct,
                self.config.stop_loss_pct,
                self.config.max_position_pct,
            )
            if size <= 0:
                self.seen.add(signal.signal_id)
                return None

        payload = {"action": action, "symbol": signal.symbol, "size": size, "market": "stocks"}
        headers = {"x-webhook-secret": self.config.webhook_secret} if self.config.webhook_secret else {}
        try:
            resp = self.http.post(self.config.webhook_url, json=payload, headers=headers)
        except Exception as exc:
            print(f"[copytrade] webhook unreachable for {signal.symbol}: {exc}, will retry")
            return None  # not marked seen -> retried next poll

        # 2xx = executed, 429 = deliberately rejected by the risk guard.
        # Both are final decisions for this signal; don't re-fire it.
        self.seen.add(signal.signal_id)
        outcome = {"signal": signal, "status_code": resp.status_code, "payload": payload}
        print(f"[copytrade] {signal.symbol} {action} size={size}: webhook -> {resp.status_code}")
        return outcome

    def run(self) -> None:
        print(
            f"[copytrade] following C2 strategies {self.config.strategy_ids}; "
            f"equity=${self.config.equity:.2f}, risk/trade={self.config.risk_per_trade_pct:.0%}, "
            f"stop={self.config.stop_loss_pct:.0%}. Create {self.config.kill_file} to halt."
        )
        while True:
            if Path(self.config.kill_file).exists():
                print(f"[copytrade] kill file {self.config.kill_file} found, exiting")
                return
            self.poll_once()
            time.sleep(self.config.poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Relay Collective2 leader signals to the webhook server")
    parser.add_argument("--strategies", nargs="+", required=True, help="Collective2 strategy (system) IDs to follow")
    parser.add_argument("--webhook-url", default="http://127.0.0.1:8000/webhook")
    parser.add_argument("--equity", type=float, default=100.0, help="Account equity used for position sizing")
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.10)
    parser.add_argument("--stop-loss-pct", type=float, default=0.06)
    parser.add_argument("--max-position-pct", type=float, default=1.0)
    parser.add_argument("--poll-seconds", type=int, default=300)
    parser.add_argument("--once", action="store_true", help="Poll once and exit (for cron or testing)")
    args = parser.parse_args()

    config = MonitorConfig(
        strategy_ids=args.strategies,
        webhook_url=args.webhook_url,
        equity=args.equity,
        risk_per_trade_pct=args.risk_per_trade_pct,
        stop_loss_pct=args.stop_loss_pct,
        max_position_pct=args.max_position_pct,
        poll_seconds=args.poll_seconds,
    )
    monitor = CopyTradeMonitor(config)
    if args.once:
        monitor.poll_once()
    else:
        monitor.run()


if __name__ == "__main__":
    main()
