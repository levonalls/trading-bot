from __future__ import annotations

import itertools
from dataclasses import replace
from typing import Callable

import pandas as pd

from trading_bot.backtest.engine import BacktestConfig, BacktestEngine
from trading_bot.backtest.metrics import compute_metrics
from trading_bot.strategies.base import Strategy, StrategyParams

# Score used to rank/optimize parameter combinations: reward return and
# Sharpe, penalize drawdown, so the search favors large gains with
# controlled losses rather than just the highest raw return.
def default_score(metrics: dict) -> float:
    return metrics["sharpe"] + metrics["total_return"] - 2 * abs(metrics["max_drawdown"])


def grid_search(
    df: pd.DataFrame,
    strategy_factory: Callable[..., Strategy],
    param_grid: dict[str, list],
    config: BacktestConfig | None = None,
    score_fn: Callable[[dict], float] = default_score,
) -> pd.DataFrame:
    """Run a strategy across the cartesian product of `param_grid` values
    and return a DataFrame of params + metrics, sorted best-first by score.

    `strategy_factory` takes the same kwargs as the strategy's params
    dataclass, e.g. `lambda **kw: TrendFollowingStrategy(TrendFollowingParams(**kw))`.
    """
    engine = BacktestEngine(config)
    keys = list(param_grid.keys())
    rows = []

    for combo in itertools.product(*param_grid.values()):
        kwargs = dict(zip(keys, combo))
        strategy = strategy_factory(**kwargs)
        result = engine.run(df, strategy)
        metrics = compute_metrics(result.equity_curve, result.trades)
        row = {**kwargs, **metrics, "score": score_fn(metrics)}
        rows.append(row)

    results = pd.DataFrame(rows)
    return results.sort_values("score", ascending=False).reset_index(drop=True)


def best_params(
    df: pd.DataFrame,
    strategy_factory: Callable[..., Strategy],
    param_grid: dict[str, list],
    config: BacktestConfig | None = None,
    score_fn: Callable[[dict], float] = default_score,
) -> dict:
    results = grid_search(df, strategy_factory, param_grid, config, score_fn)
    if results.empty:
        raise ValueError("param_grid produced no combinations")
    keys = list(param_grid.keys())
    best_row = results.iloc[0]
    # results.iloc[0] upcasts mixed int/float columns to a common dtype, so
    # restore each param's original type from the grid rather than trust it.
    params = {}
    for key in keys:
        sample = param_grid[key][0]
        value = best_row[key]
        params[key] = type(sample)(value) if isinstance(sample, (int, float)) else value
    return params
