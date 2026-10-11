"""
Self-contained ETH futures runner for Interactive Brokers paper/live trading.

Trades the CME Micro Ether futures contract (MET) by default — $0.10 per
dollar of ETH notional, far smaller than the full ETH contract — making it
practical for small accounts and paper testing.

Usage (paper mode, default):
    python -m trading_bot.eth_runner

Usage (live — requires TRADING_BOT_LIVE_CONFIRM set):
    TRADING_MODE=live TRADING_BOT_LIVE_CONFIRM=I_UNDERSTAND_LIVE_TRADING \
        python -m trading_bot.eth_runner
"""
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from trading_bot.execution.ib_broker import IBBroker
from trading_bot.execution.ccxt_broker import LIVE_CONFIRM_VALUE
from trading_bot.execution.risk import RiskGuard
from trading_bot.journal.journal import Journal, JournalEntry
from trading_bot.strategies.regime import select_strategy

# CME Micro Ether futures — $0.10/USD notional per contract, much smaller
# than full ETH (ETH = $50/USD notional). Use MET for small accounts.
DEFAULT_SYMBOL   = "MET"   # Micro Ether Trust futures on CME
DEFAULT_TIMEFRAME = "1h"
DEFAULT_POLL     = 300     # seconds between polls (5 min)

KILL_SWITCH_FILE = Path(os.environ.get("LIVE_RUNNER_KILL_FILE", "eth_runner.kill"))

_TIMEFRAME_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400,
}


@dataclass
class RunnerState:
    position: int   = 0    # -1 short, 0 flat, 1 long
    strategy: str   = ""   # last strategy name used
    notional: float = 0.0

    @classmethod
    def load(cls, path: Path) -> "RunnerState":
        if path.exists():
            return cls(**json.loads(path.read_text()))
        return cls()

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.__dict__))


def _data_is_fresh(df, timeframe: str, max_bars_old: int = 2) -> tuple[bool, str]:
    if df is None or df.empty:
        return False, "no bars returned"
    last_ts = df.index[-1]
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - last_ts).total_seconds()
    limit = _TIMEFRAME_SECONDS.get(timeframe, 3600) * max_bars_old
    if age > limit:
        return False, (
            f"latest bar is {int(age/60)} min old "
            f"(max {int(limit/60)} min for {timeframe}) — "
            "subscribe to CME Crypto market data in IBKR Account Management"
        )
    return True, ""


def _size_contracts(broker: IBBroker, symbol: str, price: float,
                    strategy, equity: float,
                    risk_pct: float, max_pct: float) -> int:
    """Size in whole contracts, accounting for the contract's point multiplier."""
    multiplier = broker.contract_multiplier(symbol)
    stop_dist  = price * strategy.params.stop_loss_pct
    risk_amt   = equity * risk_pct
    by_risk    = risk_amt / (stop_dist * multiplier) if stop_dist > 0 else 0.0
    by_cap     = (equity * max_pct) / (price * multiplier) if price > 0 else 0.0
    return int(min(by_risk, by_cap))


def run(
    symbol: str       = DEFAULT_SYMBOL,
    timeframe: str    = DEFAULT_TIMEFRAME,
    poll_seconds: int = DEFAULT_POLL,
    risk_pct: float   = 0.01,
    max_pct: float    = 0.20,
    max_iterations: int | None = None,
) -> None:
    paper = os.environ.get("TRADING_MODE", "paper") != "live"

    if not paper and os.environ.get("TRADING_BOT_LIVE_CONFIRM") != LIVE_CONFIRM_VALUE:
        raise RuntimeError(
            f"Set TRADING_BOT_LIVE_CONFIRM={LIVE_CONFIRM_VALUE} to enable live trading."
        )

    broker = IBBroker(paper=paper)
    guard  = RiskGuard(
        max_order_size=float(os.environ.get("MAX_ORDER_SIZE", "5")),
        max_daily_orders=int(os.environ.get("MAX_DAILY_ORDERS", "10")),
    )
    journal    = Journal()
    state_path = Path(f"eth_runner_state_{symbol}.json")
    state      = RunnerState.load(state_path)

    mode = "PAPER" if paper else "LIVE"
    print(f"ETH Futures Runner — {symbol} {timeframe} [{mode}]")
    print(f"Risk per trade: {risk_pct*100:.1f}%  |  Max position: {max_pct*100:.0f}% of equity")
    print(f"Last known position: {state.position}  strategy: {state.strategy or 'none'}\n")

    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        iterations += 1

        if KILL_SWITCH_FILE.exists():
            print(f"Kill switch file found — halting.")
            break

        try:
            df = broker.fetch_ohlcv(symbol, timeframe=timeframe, limit=300)

            fresh, reason = _data_is_fresh(df, timeframe)
            if not fresh:
                print(f"[{symbol}] Skipping — stale data: {reason}")
                time.sleep(poll_seconds)
                continue

            strategy, regime = select_strategy(df)
            price  = float(df["close"].iloc[-1])
            equity = broker.account_equity()

            print(f"[{symbol}] ${price:,.2f}  |  {regime}  →  {strategy.name}")

            signal          = strategy.signals(df)
            target_position = int(signal.iloc[-1])

            if target_position != state.position:
                side = "buy" if target_position > state.position else "sell"
                size = _size_contracts(broker, symbol, price, strategy,
                                       equity, risk_pct, max_pct)

                allowed, reason = guard.check(size)
                if not allowed:
                    print(f"  Skipped by risk guard: {reason}")
                    journal.log(JournalEntry(
                        entry_date=date.today().isoformat(),
                        strategy=strategy.name,
                        symbol=symbol,
                        metrics={"rejected": True, "regime": regime.regime},
                        notes=f"risk guard: {reason}",
                    ))
                elif size <= 0:
                    print(f"  Skipped: sized to 0 contracts "
                          f"(equity ${equity:,.0f}, price ${price:,.0f})")
                else:
                    order = broker.place_order(symbol, side, size)
                    guard.record_order()
                    print(f"  {state.position} → {target_position}: "
                          f"{side.upper()} {size} {symbol} @ ~${price:,.2f}  {order}")
                    journal.log(JournalEntry(
                        entry_date=date.today().isoformat(),
                        strategy=strategy.name,
                        symbol=symbol,
                        metrics={
                            "side": side, "size": size, "price": price,
                            "equity": equity, "regime": regime.regime,
                            "adx": round(regime.adx, 2),
                            "mode": "paper" if paper else "live",
                        },
                        notes=f"regime={regime.regime} adx={regime.adx:.1f} "
                              f"atr_pct={regime.atr_pct*100:.2f}%",
                    ))
                    state.position = target_position
                    state.strategy = strategy.name
                    state.notional = 0.0 if target_position == 0 else size * price
                    state.save(state_path)
            else:
                print(f"  No change — position remains {state.position}")

        except Exception as exc:
            print(f"[{symbol}] Error: {exc}")
            journal.log(JournalEntry(
                entry_date=date.today().isoformat(),
                strategy="eth_runner",
                symbol=symbol,
                metrics={"error": True},
                notes=str(exc),
            ))

        if max_iterations is None or iterations < max_iterations:
            time.sleep(poll_seconds)

    broker.disconnect()
    print("Runner stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-strategy ETH futures runner for Interactive Brokers"
    )
    parser.add_argument("--symbol",       default=DEFAULT_SYMBOL,
                        help="Futures symbol (default: MET = Micro Ether)")
    parser.add_argument("--timeframe",    default=DEFAULT_TIMEFRAME,
                        help="Bar timeframe: 1m 5m 15m 30m 1h 4h 1d (default: 1h)")
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL)
    parser.add_argument("--risk-pct",     type=float, default=0.01,
                        help="Fraction of equity to risk per trade (default: 0.01 = 1%%)")
    parser.add_argument("--max-pct",      type=float, default=0.20,
                        help="Max notional as fraction of equity (default: 0.20 = 20%%)")
    args = parser.parse_args()

    run(
        symbol       = args.symbol,
        timeframe    = args.timeframe,
        poll_seconds = args.poll_seconds,
        risk_pct     = args.risk_pct,
        max_pct      = args.max_pct,
    )


if __name__ == "__main__":
    main()
