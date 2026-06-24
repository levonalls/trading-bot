from trading_bot.execution.risk import RiskGuard


def test_rejects_oversized_order():
    guard = RiskGuard(max_order_size=1.0)
    allowed, _ = guard.check(2.0)
    assert not allowed


def test_allows_normal_order_and_counts_it():
    guard = RiskGuard(max_order_size=1.0, max_daily_orders=2)
    allowed, _ = guard.check(0.5)
    assert allowed
    guard.record_order()
    guard.record_order()
    allowed, reason = guard.check(0.5)
    assert not allowed
    assert "max_daily_orders" in reason


def test_kill_switch():
    guard = RiskGuard()
    guard.kill()
    allowed, reason = guard.check(0.1)
    assert not allowed
    assert "kill switch" in reason
    guard.rearm()
    allowed, _ = guard.check(0.1)
    assert allowed
