from __future__ import annotations

import numpy as np
import pandas as pd


def max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    return drawdown.min()


def sharpe_ratio(returns: pd.Series, periods_per_year: int) -> float:
    if returns.std() == 0 or returns.empty:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(periods_per_year))


def compute_metrics(equity: pd.Series, trades: pd.DataFrame, periods_per_year: int = 365) -> dict:
    returns = equity.pct_change().dropna()
    total_return = equity.iloc[-1] / equity.iloc[0] - 1 if len(equity) > 1 else 0.0

    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] <= 0]
    win_rate = len(wins) / len(trades) if len(trades) else 0.0
    gross_profit = wins["pnl"].sum() if len(wins) else 0.0
    gross_loss = -losses["pnl"].sum() if len(losses) else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

    return {
        "total_return": total_return,
        "max_drawdown": max_drawdown(equity),
        "sharpe": sharpe_ratio(returns, periods_per_year),
        "num_trades": len(trades),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_win": wins["pnl"].mean() if len(wins) else 0.0,
        "avg_loss": losses["pnl"].mean() if len(losses) else 0.0,
    }
