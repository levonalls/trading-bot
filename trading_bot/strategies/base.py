from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class StrategyParams:
    """Base container for strategy parameters; subclasses add fields."""

    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.06


class Strategy(ABC):
    """A strategy turns OHLCV data into a position signal series.

    Signal convention: 1 = long, -1 = short, 0 = flat. Backtest engine
    consumes this series directly, and the same params drive the Pine
    Script generator so the logic matches what runs in Python.
    """

    name: str = "strategy"

    def __init__(self, params: StrategyParams):
        self.params = params

    @abstractmethod
    def signals(self, df: pd.DataFrame) -> pd.Series:
        """Return a position signal series indexed like df, in {-1, 0, 1}."""
        raise NotImplementedError

    def pine_params(self) -> dict:
        """Params exposed to the Pine Script generator."""
        return self.params.__dict__
