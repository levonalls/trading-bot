from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from trading_bot.data.fetch import fetch_ohlcv
from trading_bot.execution.ccxt_broker import CcxtBroker
from trading_bot.execution.risk import RiskGuard
from trading_bot.journal.journal import Journal, JournalEntry
from trading_bot.strategies.breakout import BreakoutStrategy
from trading_bot.strategies.mean_reversion import MeanReversionStrategy
from trading_bot.strategies.trend_following import TrendFollowingStrategy

STRATEGIES = {
    "trend_following": TrendFollowingStrategy,
    "mean_reversion": MeanReversionStrategy,
    "breakout": BreakoutStrategy,
}

# Touch this file to halt the live runner before its next poll, independent
# of the webhook server's in-memory kill switch (this one survives restarts
# and works even if you can't reach the webhook process).
KILL_SWITCH_FILE = Path(os.environ.get("LIVE_RUNNER_KILL_FILE", "live_runner.kill"))


@dataclass
class RunnerState:
    position: int = 0  # -1, 0, 1 -- last position this runner has taken

    @classmethod
    def load(cls, path: Path) -> "RunnerState":
        if path.exists():
            return cls(**json.loads(path.read_text()))
        return cls()

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.__dict__))


def run_live(
    strategy_name: str,
    symbol: str,
    timeframe: str,
    poll_seconds: int,
    risk_per_trade_pct: float,
    max_position_pct: float = 0.20,
    max_iterations: int | None = None,
) -> None:
    """Polls live OHLCV data, computes the strategy's signal on the latest
    closed bar, and places an order only when the signal changes from the
    last known position. State (current position) is persisted to disk so
    restarting the process doesn't re-fire an order it already placed.

    Safety is layered, not just here:
    - CcxtBroker itself refuses live orders without TRADING_BOT_LIVE_CONFIRM.
    - RiskGuard caps order size and orders/day, same as the webhook path.
    - KILL_SWITCH_FILE is checked every loop and halts immediately if present.
    """
    paper = os.environ.get("TRADING_MODE", "paper") != "live"
    exchange_id = os.environ.get("CRYPTO_EXCHANGE", "binance")

    broker = CcxtBroker(exchange_id=exchange_id, paper=paper)
    risk_guard = RiskGuard(
        max_order_size=float(os.environ.get("MAX_ORDER_SIZE", "1.0")),
        max_daily_orders=int(os.environ.get("MAX_DAILY_ORDERS", "50")),
    )
    journal = Journal()
    strategy = STRATEGIES[strategy_name]()

    state_path = Path(f"live_runner_state_{strategy_name}_{symbol.replace('/', '_')}.json")
    state = RunnerState.load(state_path)

    print(f"Live runner started: {strategy_name} on {symbol} ({exchange_id}, "
          f"{'PAPER' if paper else 'LIVE'}). Last known position: {state.position}")

    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        iterations += 1

        if KILL_SWITCH_FILE.exists():
            print(f"Kill switch file {KILL_SWITCH_FILE} present — halting.")
            break

        try:
            df = fetch_ohlcv(symbol, timeframe=timeframe, limit=300, exchange=exchange_id)
            signal = strategy.signals(df)
            target_position = int(signal.iloc[-1])

            if target_position != state.position:
                side = "buy" if target_position > state.position else "sell"
                size = _position_size(broker, symbol, strategy, risk_per_trade_pct, max_position_pct, paper)

                allowed, reason = risk_guard.check(size)
                if not allowed:
                    print(f"Order skipped by risk guard: {reason}")
                    journal.log(JournalEntry(
                        entry_date=date.today().isoformat(),
                        strategy=strategy_name,
                        symbol=symbol,
                        metrics={"rejected": True},
                        notes=f"live runner rejected: {reason}",
                    ))
                else:
                    order = broker.place_order(symbol, side, size)
                    risk_guard.record_order()
                    journal.log(JournalEntry(
                        entry_date=date.today().isoformat(),
                        strategy=strategy_name,
                        symbol=symbol,
                        metrics={"side": side, "size": size, "mode": "paper" if paper else "live"},
                        notes=f"live runner order: {order}",
                    ))
                    print(f"Position {state.position} -> {target_position}: placed {side} {size} {symbol}: {order}")
                    state.position = target_position
                    state.save(state_path)
            else:
                print(f"No change. Position remains {state.position}.")

        except Exception as exc:  # noqa: BLE001 - keep the loop alive across transient API errors
            print(f"Error in live runner iteration: {exc}")
            journal.log(JournalEntry(
                entry_date=date.today().isoformat(),
                strategy=strategy_name,
                symbol=symbol,
                metrics={"error": True},
                notes=f"live runner exception: {exc}",
            ))

        if max_iterations is None or iterations < max_iterations:
            time.sleep(poll_seconds)


def _position_size(
    broker: CcxtBroker,
    symbol: str,
    strategy,
    risk_per_trade_pct: float,
    max_position_pct: float,
    paper: bool,
) -> float:
    """Size a position so a stop-loss hit risks `risk_per_trade_pct` of
    available quote balance, mirroring the backtest engine's sizing logic.
    Caps the trade's notional value (size * price) to at most
    `max_position_pct` of equity, regardless of stop distance, so a tight
    stop on a volatile symbol can't blow past a sane fraction of the
    portfolio in a single trade.
    """
    quote = symbol.split("/")[1]
    price = broker.client.fetch_ticker(symbol)["last"]

    # Quote currencies like USD/USDC/USDT are economically interchangeable
    # 1:1 for sizing purposes, so check all of them, not just the literal
    # quote in the trading pair -- a USD pair shouldn't fail to size just
    # because the balance happens to be held in USDC.
    stablecoin_aliases = {"USD", "USDC", "USDT"}
    candidates = stablecoin_aliases if quote in stablecoin_aliases else {quote}

    try:
        balance = broker.fetch_balance()
        totals = balance.get("total", {}) or {}
        equity = sum(totals.get(c, 0.0) or 0.0 for c in candidates)
    except Exception:
        equity = 0.0

    if not equity:
        equity = float(os.environ.get("ASSUMED_EQUITY", "0"))
        if not equity:
            raise RuntimeError(
                f"Could not determine balance in any of {sorted(candidates)} "
                "and no ASSUMED_EQUITY fallback is set."
            )

    stop_distance = price * strategy.params.stop_loss_pct
    risk_amount = equity * risk_per_trade_pct
    size = risk_amount / stop_distance if stop_distance > 0 else 0.0

    max_size = (equity * max_position_pct) / price if price > 0 else 0.0
    size = min(size, max_size)

    return round(size, 8)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a strategy live/paper against an exchange")
    parser.add_argument("--strategy", choices=STRATEGIES.keys(), required=True)
    parser.add_argument("--symbol", required=True, help="e.g. BTC/USD")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--poll-seconds", type=int, default=300)
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.01)
    parser.add_argument("--max-position-pct", type=float, default=0.20,
                         help="Hard cap on a single trade's notional size, as a fraction of equity")
    args = parser.parse_args()

    run_live(
        args.strategy,
        args.symbol,
        args.timeframe,
        args.poll_seconds,
        args.risk_per_trade_pct,
        args.max_position_pct,
    )


if __name__ == "__main__":
    main()
