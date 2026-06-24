from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trading_bot.strategies.base import Strategy


@dataclass
class BacktestConfig:
    initial_capital: float = 10_000.0
    risk_per_trade_pct: float = 0.01  # fraction of equity risked per trade (sized via stop distance)
    fee_pct: float = 0.0005  # taker fee, applied on entry and exit notional
    max_drawdown_halt: float = 0.25  # stop opening new trades once equity drawdown exceeds this


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: int
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    exit_reason: str


class BacktestEngine:
    """Bar-by-bar backtest with stop loss, take profit, fixed-risk position
    sizing, fees, and a max-drawdown circuit breaker so the optimizer is
    pushed toward strategies that cap large losses, not just raw return.
    """

    def __init__(self, config: BacktestConfig | None = None):
        self.config = config or BacktestConfig()

    def run(self, df: pd.DataFrame, strategy: Strategy) -> "BacktestResult":
        cfg = self.config
        signal = strategy.signals(df)
        stop_pct = strategy.params.stop_loss_pct
        tp_pct = strategy.params.take_profit_pct

        equity = cfg.initial_capital
        equity_curve = []
        trades: list[Trade] = []

        position = 0
        entry_price = entry_time = size = stop_price = tp_price = None
        peak_equity = equity

        for i, (ts, row) in enumerate(df.iterrows()):
            sig = signal.iloc[i]
            price = row["close"]

            if position != 0:
                hit_stop = (position == 1 and row["low"] <= stop_price) or (
                    position == -1 and row["high"] >= stop_price
                )
                hit_tp = (position == 1 and row["high"] >= tp_price) or (
                    position == -1 and row["low"] <= tp_price
                )
                flat_signal = sig != position

                exit_price = None
                reason = None
                if hit_stop:
                    exit_price, reason = stop_price, "stop_loss"
                elif hit_tp:
                    exit_price, reason = tp_price, "take_profit"
                elif flat_signal:
                    exit_price, reason = price, "signal_flip"

                if exit_price is not None:
                    pnl = position * (exit_price - entry_price) * size
                    pnl -= cfg.fee_pct * exit_price * size
                    equity += pnl
                    trades.append(
                        Trade(entry_time, ts, position, entry_price, exit_price, size, pnl, reason)
                    )
                    position = 0

            peak_equity = max(peak_equity, equity)
            drawdown = (equity - peak_equity) / peak_equity if peak_equity else 0.0

            if position == 0 and sig != 0 and drawdown > -cfg.max_drawdown_halt:
                entry_price = price
                entry_time = ts
                stop_distance = entry_price * stop_pct
                risk_amount = equity * cfg.risk_per_trade_pct
                size = risk_amount / stop_distance if stop_distance > 0 else 0.0
                equity -= cfg.fee_pct * entry_price * size
                position = sig
                stop_price = entry_price - sig * stop_distance
                tp_price = entry_price + sig * entry_price * tp_pct

            equity_curve.append(equity)

        equity_series = pd.Series(equity_curve, index=df.index, name="equity")
        trade_columns = [
            "entry_time", "exit_time", "direction", "entry_price",
            "exit_price", "size", "pnl", "exit_reason",
        ]
        trades_df = pd.DataFrame([t.__dict__ for t in trades], columns=trade_columns)
        return BacktestResult(equity_series, trades_df, strategy.name)


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: pd.DataFrame
    strategy_name: str
