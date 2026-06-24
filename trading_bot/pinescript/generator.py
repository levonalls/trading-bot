from __future__ import annotations

from pathlib import Path

from trading_bot.strategies.base import Strategy

TEMPLATES_DIR = Path(__file__).parent / "templates"


def generate_pine_script(strategy: Strategy, symbol: str = "BTCUSDT") -> str:
    """Render a strategy's Python params into its Pine Script template so
    the TradingView version matches the logic that was backtested.
    """
    template_path = TEMPLATES_DIR / f"{strategy.name}.pine"
    if not template_path.exists():
        raise FileNotFoundError(f"No Pine template for strategy '{strategy.name}'")

    template = template_path.read_text()
    params = {**strategy.pine_params(), "symbol": symbol}
    return template.format(**params)
