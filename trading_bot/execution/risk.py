from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class RiskGuard:
    """Lightweight guardrails enforced in front of every live/paper order.

    Kept deliberately simple (no live PnL feed required): caps order size,
    caps how many orders can fire in a day (protects against a runaway
    TradingView alert loop), and exposes a manual kill switch that halts
    all trading until explicitly re-armed.
    """

    max_order_size: float = 1.0
    max_daily_orders: int = 50
    _killed: bool = field(default=False, init=False)
    _order_count: int = field(default=0, init=False)
    _count_date: str = field(default_factory=lambda: date.today().isoformat(), init=False)

    def kill(self) -> None:
        self._killed = True

    def rearm(self) -> None:
        self._killed = False

    def _reset_if_new_day(self) -> None:
        today = date.today().isoformat()
        if today != self._count_date:
            self._count_date = today
            self._order_count = 0

    def check(self, size: float) -> tuple[bool, str]:
        self._reset_if_new_day()
        if self._killed:
            return False, "kill switch engaged"
        if size > self.max_order_size:
            return False, f"size {size} exceeds max_order_size {self.max_order_size}"
        if self._order_count >= self.max_daily_orders:
            return False, f"max_daily_orders ({self.max_daily_orders}) reached"
        return True, "ok"

    def record_order(self) -> None:
        self._reset_if_new_day()
        self._order_count += 1
