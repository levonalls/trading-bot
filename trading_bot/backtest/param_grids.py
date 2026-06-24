from __future__ import annotations

from trading_bot.strategies.breakout import BreakoutParams, BreakoutStrategy
from trading_bot.strategies.mean_reversion import MeanReversionParams, MeanReversionStrategy
from trading_bot.strategies.trend_following import TrendFollowingParams, TrendFollowingStrategy

# Default search spaces and (params-class, strategy-class) pairs for each
# named strategy, used by the CLI's optimize/walk-forward commands.
DEFAULT_GRIDS = {
    "trend_following": {
        "grid": {
            "fast_ema": [10, 20, 30],
            "slow_ema": [40, 50, 60],
            "trend_ema": [150, 200],
            "stop_loss_pct": [0.01, 0.02, 0.03],
            "take_profit_pct": [0.04, 0.06, 0.08],
        },
        "params_cls": TrendFollowingParams,
        "strategy_cls": TrendFollowingStrategy,
    },
    "mean_reversion": {
        "grid": {
            "bb_window": [14, 20, 30],
            "bb_std": [1.5, 2.0, 2.5],
            "rsi_window": [10, 14],
            "stop_loss_pct": [0.01, 0.02],
            "take_profit_pct": [0.03, 0.05],
        },
        "params_cls": MeanReversionParams,
        "strategy_cls": MeanReversionStrategy,
    },
    "breakout": {
        "grid": {
            "entry_window": [10, 20, 40],
            "exit_window": [5, 10, 20],
            "stop_loss_pct": [0.01, 0.02, 0.03],
            "take_profit_pct": [0.04, 0.06, 0.1],
        },
        "params_cls": BreakoutParams,
        "strategy_cls": BreakoutStrategy,
    },
}


def make_factory(name: str):
    spec = DEFAULT_GRIDS[name]
    params_cls, strategy_cls = spec["params_cls"], spec["strategy_cls"]
    return lambda **kw: strategy_cls(params_cls(**kw))
