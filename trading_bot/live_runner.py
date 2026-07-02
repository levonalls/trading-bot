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
    notional: float = 0.0  # size * price of the currently open position, for portfolio-wide budgeting
    entry_price: float = 0.0  # fill price of the open position, for stop-loss/take-profit checks
    size: float = 0.0  # base-currency size of the open position, so an exit closes exactly what was opened

    @classmethod
    def load(cls, path: Path) -> "RunnerState":
        if path.exists():
            return cls(**json.loads(path.read_text()))
        return cls()

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.__dict__))


def _apply_params(strategy, overrides: dict) -> None:
    """Apply optimizer-tuned param overrides to a strategy instance."""
    for key, value in overrides.items():
        current = getattr(strategy.params, key, None)
        if current is not None:
            setattr(strategy.params, key, type(current)(value))


def _check_protective_exit(
    broker: CcxtBroker,
    risk_guard: RiskGuard,
    journal: Journal,
    strategy_name: str,
    symbol: str,
    strategy,
    state: RunnerState,
    state_path: Path,
    paper: bool,
) -> bool:
    """Close the open position if the live price has hit the strategy's
    stop-loss or take-profit level. Returns True if the position was closed.

    The backtest engine enforces stop_loss_pct/take_profit_pct on every bar,
    but signal-flip exits alone can ride a winner all the way back to a loss
    live — this makes the live runner honor the same protective levels.
    """
    if state.position == 0 or state.entry_price <= 0 or state.size <= 0:
        return False

    price = broker.client.fetch_ticker(symbol)["last"]
    # Signed return of the open position: positive means the trade is winning.
    gain_pct = (price - state.entry_price) / state.entry_price * state.position

    if gain_pct <= -strategy.params.stop_loss_pct:
        reason = "stop_loss"
    elif gain_pct >= strategy.params.take_profit_pct:
        reason = "take_profit"
    else:
        return False

    side = "sell" if state.position > 0 else "buy"
    allowed, guard_reason = risk_guard.check(state.size)
    if not allowed:
        print(f"[{symbol}] Protective exit ({reason}) blocked by risk guard: {guard_reason}")
        return False

    order = broker.place_order(symbol, side, state.size)
    risk_guard.record_order()
    journal.log(JournalEntry(
        entry_date=date.today().isoformat(),
        strategy=strategy_name,
        symbol=symbol,
        metrics={"side": side, "size": state.size, "exit": reason,
                 "gain_pct": round(gain_pct, 6), "mode": "paper" if paper else "live"},
        notes=f"protective exit ({reason}): {order}",
    ))
    print(f"[{symbol}] {reason.upper()} hit at {price} (entry {state.entry_price}, "
          f"{gain_pct:+.2%}): placed {side} {state.size} {symbol}: {order}")

    state.position = 0
    state.notional = 0.0
    state.entry_price = 0.0
    state.size = 0.0
    state.save(state_path)
    return True


def run_live(
    strategy_name: str,
    symbol: str,
    timeframe: str,
    poll_seconds: int,
    risk_per_trade_pct: float,
    max_position_pct: float = 0.20,
    params_override: dict | None = None,
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
    if params_override:
        _apply_params(strategy, params_override)

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
            if _check_protective_exit(broker, risk_guard, journal, strategy_name, symbol,
                                      strategy, state, state_path, paper):
                # Closed at stop/target this cycle; re-evaluate entries next poll.
                if max_iterations is None or iterations < max_iterations:
                    time.sleep(poll_seconds)
                continue

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
                    price = broker.client.fetch_ticker(symbol)["last"]
                    state.position = target_position
                    state.notional = 0.0 if target_position == 0 else size * price
                    state.entry_price = 0.0 if target_position == 0 else price
                    state.size = 0.0 if target_position == 0 else size
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


def run_live_multi(
    pairs: list[tuple[str, str]],
    timeframe: str,
    poll_seconds: int,
    risk_per_trade_pct: float,
    max_portfolio_pct: float = 0.20,
    params_override: dict | None = None,
    max_iterations: int | None = None,
) -> None:
    """Like `run_live`, but manages several (strategy, symbol) pairs against
    one shared equity budget. `max_portfolio_pct` caps the *combined*
    notional exposure across all pairs at once -- e.g. running 3 coins at
    max_portfolio_pct=0.20 means those 3 trades together can use at most 20%
    of equity, not 20% each, so adding more symbols can't silently triple
    your total risk.
    """
    paper = os.environ.get("TRADING_MODE", "paper") != "live"
    exchange_id = os.environ.get("CRYPTO_EXCHANGE", "binance")

    broker = CcxtBroker(exchange_id=exchange_id, paper=paper)
    risk_guard = RiskGuard(
        max_order_size=float(os.environ.get("MAX_ORDER_SIZE", "1.0")),
        max_daily_orders=int(os.environ.get("MAX_DAILY_ORDERS", "50")),
    )
    journal = Journal()

    managed = []
    for strategy_name, symbol in pairs:
        state_path = Path(f"live_runner_state_{strategy_name}_{symbol.replace('/', '_')}.json")
        strategy = STRATEGIES[strategy_name]()
        if params_override:
            _apply_params(strategy, params_override)
        managed.append({
            "strategy_name": strategy_name,
            "symbol": symbol,
            "strategy": strategy,
            "state_path": state_path,
            "state": RunnerState.load(state_path),
        })

    print(f"Multi-symbol live runner started ({exchange_id}, {'PAPER' if paper else 'LIVE'}) "
          f"managing: {[(m['strategy_name'], m['symbol']) for m in managed]}")

    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        iterations += 1

        if KILL_SWITCH_FILE.exists():
            print(f"Kill switch file {KILL_SWITCH_FILE} present — halting.")
            break

        for m in managed:
            strategy_name, symbol, strategy, state_path, state = (
                m["strategy_name"], m["symbol"], m["strategy"], m["state_path"], m["state"],
            )
            try:
                if _check_protective_exit(broker, risk_guard, journal, strategy_name, symbol,
                                          strategy, state, state_path, paper):
                    # Closed at stop/target this cycle; re-evaluate entries next poll.
                    continue

                df = fetch_ohlcv(symbol, timeframe=timeframe, limit=300, exchange=exchange_id)
                signal = strategy.signals(df)
                target_position = int(signal.iloc[-1])

                if target_position != state.position:
                    side = "buy" if target_position > state.position else "sell"

                    equity = _account_equity(broker, symbol)
                    committed_elsewhere = sum(
                        other["state"].notional for other in managed if other is not m
                    )
                    remaining_budget = max(equity * max_portfolio_pct - committed_elsewhere, 0.0)
                    price = broker.client.fetch_ticker(symbol)["last"]
                    size = _size_for_notional_cap(price, equity, remaining_budget, risk_per_trade_pct, strategy)

                    allowed, reason = risk_guard.check(size)
                    if not allowed:
                        print(f"[{symbol}] Order skipped by risk guard: {reason}")
                        journal.log(JournalEntry(
                            entry_date=date.today().isoformat(),
                            strategy=strategy_name,
                            symbol=symbol,
                            metrics={"rejected": True},
                            notes=f"multi live runner rejected: {reason}",
                        ))
                    else:
                        order = broker.place_order(symbol, side, size)
                        risk_guard.record_order()
                        journal.log(JournalEntry(
                            entry_date=date.today().isoformat(),
                            strategy=strategy_name,
                            symbol=symbol,
                            metrics={"side": side, "size": size, "mode": "paper" if paper else "live"},
                            notes=f"multi live runner order: {order}",
                        ))
                        print(f"[{symbol}] Position {state.position} -> {target_position}: "
                              f"placed {side} {size} {symbol}: {order}")
                        state.position = target_position
                        state.notional = 0.0 if target_position == 0 else size * price
                        state.entry_price = 0.0 if target_position == 0 else price
                        state.size = 0.0 if target_position == 0 else size
                        state.save(state_path)
                else:
                    print(f"[{symbol}] No change. Position remains {state.position}.")

            except Exception as exc:  # noqa: BLE001 - keep the loop alive across transient API errors
                print(f"[{symbol}] Error in live runner iteration: {exc}")
                journal.log(JournalEntry(
                    entry_date=date.today().isoformat(),
                    strategy=strategy_name,
                    symbol=symbol,
                    metrics={"error": True},
                    notes=f"multi live runner exception: {exc}",
                ))

        if max_iterations is None or iterations < max_iterations:
            time.sleep(poll_seconds)


def _account_equity(broker: CcxtBroker, symbol: str) -> float:
    """USD-equivalent equity, treating USD/USDC/USDT as interchangeable so a
    USD pair doesn't fail to size just because the balance is held in USDC.
    """
    quote = symbol.split("/")[1]
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
    return equity


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
    price = broker.client.fetch_ticker(symbol)["last"]
    equity = _account_equity(broker, symbol)
    max_notional = equity * max_position_pct
    return _size_for_notional_cap(price, equity, max_notional, risk_per_trade_pct, strategy)


def _size_for_notional_cap(price: float, equity: float, max_notional: float, risk_per_trade_pct: float, strategy) -> float:
    stop_distance = price * strategy.params.stop_loss_pct
    risk_amount = equity * risk_per_trade_pct
    size = risk_amount / stop_distance if stop_distance > 0 else 0.0

    max_size = max(max_notional, 0.0) / price if price > 0 else 0.0
    size = min(size, max_size)

    return round(size, 8)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a strategy live/paper against an exchange")
    parser.add_argument("--strategy", choices=STRATEGIES.keys(), help="Single-symbol mode")
    parser.add_argument("--symbol", help="e.g. BTC/USD (single-symbol mode)")
    parser.add_argument("--pairs", nargs="+",
                         help="Multi-symbol mode: one or more 'strategy:symbol' entries, "
                              "e.g. --pairs mean_reversion:ADA/USD mean_reversion:SOL/USD")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--poll-seconds", type=int, default=300)
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.01)
    parser.add_argument("--max-position-pct", type=float, default=0.20,
                         help="Single-symbol mode: cap on that trade's notional, as a fraction of equity")
    parser.add_argument("--max-portfolio-pct", type=float, default=0.20,
                         help="Multi-symbol mode: cap on the COMBINED notional of all pairs, as a fraction of equity")
    parser.add_argument("--params", default=None,
                         help="JSON string of strategy param overrides from the optimizer, "
                              "e.g. '{\"bb_window\": 30, \"bb_std\": 2.5, \"rsi_window\": 10}'")
    args = parser.parse_args()

    params_override = json.loads(args.params) if args.params else None

    if args.pairs:
        pairs = []
        for entry in args.pairs:
            strategy_name, _, symbol = entry.partition(":")
            if not symbol or strategy_name not in STRATEGIES:
                parser.error(f"invalid --pairs entry '{entry}', expected 'strategy:symbol' "
                             f"with strategy in {sorted(STRATEGIES)}")
            pairs.append((strategy_name, symbol))
        run_live_multi(
            pairs,
            args.timeframe,
            args.poll_seconds,
            args.risk_per_trade_pct,
            args.max_portfolio_pct,
            params_override,
        )
    else:
        if not args.strategy or not args.symbol:
            parser.error("either --pairs, or both --strategy and --symbol, are required")
        run_live(
            args.strategy,
            args.symbol,
            args.timeframe,
            args.poll_seconds,
            args.risk_per_trade_pct,
            args.max_position_pct,
            params_override,
        )


if __name__ == "__main__":
    main()
