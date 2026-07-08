from __future__ import annotations

from trading_bot.strategies.breakout import BreakoutParams, BreakoutStrategy
from trading_bot.strategies.gap_and_go import GapAndGoParams, GapAndGoStrategy
from trading_bot.strategies.mean_reversion import MeanReversionParams, MeanReversionStrategy
from trading_bot.strategies.opening_range_breakout import (
    OpeningRangeBreakoutParams,
    OpeningRangeBreakoutStrategy,
)
from trading_bot.strategies.trend_following import TrendFollowingParams, TrendFollowingStrategy
from trading_bot.strategies.vwap_reversion import VwapReversionParams, VwapReversionStrategy

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
    # Intraday strategies: optimize on minute-bar data (e.g. cli fetch-stocks
    # --timeframe 5Min); the stop/take-profit ranges are day-trade scale.
    "opening_range_breakout": {
        "grid": {
            "range_bars": [3, 6, 12],
            "stop_loss_pct": [0.005, 0.01, 0.015],
            "take_profit_pct": [0.01, 0.02, 0.03],
        },
        "params_cls": OpeningRangeBreakoutParams,
        "strategy_cls": OpeningRangeBreakoutStrategy,
    },
    "vwap_reversion": {
        "grid": {
            "band_pct": [0.003, 0.005, 0.01],
            "warmup_bars": [3, 6],
            "stop_loss_pct": [0.005, 0.01],
            "take_profit_pct": [0.01, 0.015, 0.02],
        },
        "params_cls": VwapReversionParams,
        "strategy_cls": VwapReversionStrategy,
    },
    "gap_and_go": {
        "grid": {
            "min_gap_pct": [0.01, 0.02, 0.03],
            "confirm_bars": [1, 2, 3],
            "stop_loss_pct": [0.01, 0.015, 0.02],
            "take_profit_pct": [0.02, 0.03, 0.05],
        },
        "params_cls": GapAndGoParams,
        "strategy_cls": GapAndGoStrategy,
    },
}


def make_factory(name: str):
    spec = DEFAULT_GRIDS[name]
    params_cls, strategy_cls = spec["params_cls"], spec["strategy_cls"]
    return lambda **kw: strategy_cls(params_cls(**kw))
