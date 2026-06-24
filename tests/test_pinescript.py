from trading_bot.pinescript.generator import generate_pine_script
from trading_bot.strategies.breakout import BreakoutStrategy
from trading_bot.strategies.mean_reversion import MeanReversionStrategy
from trading_bot.strategies.trend_following import TrendFollowingStrategy


def test_generate_all_pine_scripts():
    for strategy_cls in (TrendFollowingStrategy, MeanReversionStrategy, BreakoutStrategy):
        script = generate_pine_script(strategy_cls(), symbol="BTCUSDT")
        assert "//@version=5" in script
        assert "BTCUSDT" in script
