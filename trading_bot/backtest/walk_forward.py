from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from trading_bot.backtest.engine import BacktestConfig, BacktestEngine
from trading_bot.backtest.metrics import compute_metrics
from trading_bot.backtest.optimize import best_params, default_score
from trading_bot.strategies.base import Strategy


@dataclass
class WalkForwardWindow:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    best_params: dict
    test_metrics: dict


def walk_forward_optimize(
    df: pd.DataFrame,
    strategy_factory: Callable[..., Strategy],
    param_grid: dict[str, list],
    train_bars: int,
    test_bars: int,
    step_bars: int | None = None,
    config: BacktestConfig | None = None,
    score_fn: Callable[[dict], float] = default_score,
) -> list[WalkForwardWindow]:
    """Rolling walk-forward optimization: for each window, fit params on the
    train slice via grid search, then evaluate those params out-of-sample on
    the following test slice. This is the standard guard against
    overfitting a single in-sample backtest.
    """
    step_bars = step_bars or test_bars
    engine = BacktestEngine(config)
    windows: list[WalkForwardWindow] = []

    start = 0
    n = len(df)
    while start + train_bars + test_bars <= n:
        train = df.iloc[start : start + train_bars]
        test = df.iloc[start + train_bars : start + train_bars + test_bars]

        params = best_params(train, strategy_factory, param_grid, config, score_fn)
        strategy = strategy_factory(**params)
        result = engine.run(test, strategy)
        test_metrics = compute_metrics(result.equity_curve, result.trades)

        windows.append(
            WalkForwardWindow(
                train_start=train.index[0],
                train_end=train.index[-1],
                test_start=test.index[0],
                test_end=test.index[-1],
                best_params=params,
                test_metrics=test_metrics,
            )
        )
        start += step_bars

    return windows


def summarize_windows(windows: list[WalkForwardWindow]) -> dict:
    """Aggregate out-of-sample performance across all walk-forward windows."""
    if not windows:
        return {}
    returns = [w.test_metrics["total_return"] for w in windows]
    drawdowns = [w.test_metrics["max_drawdown"] for w in windows]
    sharpes = [w.test_metrics["sharpe"] for w in windows]
    compounded = 1.0
    for r in returns:
        compounded *= 1 + r

    return {
        "num_windows": len(windows),
        "compounded_oos_return": compounded - 1,
        "avg_oos_return": sum(returns) / len(returns),
        "worst_oos_drawdown": min(drawdowns),
        "avg_oos_sharpe": sum(sharpes) / len(sharpes),
    }
