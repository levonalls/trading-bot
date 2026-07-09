from __future__ import annotations

import argparse
from dataclasses import dataclass

import pandas as pd

from trading_bot.data.alpaca_data import fetch_stock_bars

# Liquid, fractional-friendly names across sectors — a starting universe for
# swing candidates, not a recommendation list. Override with --symbols.
DEFAULT_UNIVERSE = [
    "SPY", "AAPL", "MSFT", "NVDA", "AMD", "TSLA", "META", "GOOGL", "AMZN",
    "PLTR", "HOOD", "SOFI", "COIN", "UBER", "INTC", "F",
]


@dataclass
class StockScreenResult:
    symbol: str
    close: float
    ret_1m: float
    ret_3m: float
    rsi_14: float
    atr_pct: float
    dist_from_20d_high: float
    trend: str  # "up" | "down" | "flat" from 20/50 SMA state
    setup: str  # which playbook the current tape fits, if any
    score: float


def rsi(close: pd.Series, window: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, pd.NA)
    # Zero average loss -> rs is NA -> RSI is 100 by convention (pure uptrend).
    return float((100 - 100 / (1 + rs)).fillna(100).iloc[-1])


def atr_pct(df: pd.DataFrame, window: int = 14) -> float:
    prev_close = df["close"].shift()
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return float((tr.rolling(window).mean() / df["close"]).iloc[-1])


def classify(close: pd.Series, r: float, dist_high: float, trend: str) -> tuple[str, float]:
    """Match the current tape to one of the bot's swing playbooks.

    Returns (setup, score); score orders candidates within and across
    setups — it rewards trend alignment and proximity to a sensible entry,
    not raw past return (yesterday's biggest gainer is not a setup).
    """
    ret_1m = float(close.iloc[-1] / close.iloc[-21] - 1) if len(close) > 21 else 0.0

    if trend == "up" and -0.08 <= dist_high <= -0.02 and 35 <= r <= 55:
        # Uptrend resting: pulled back off the highs without breaking down.
        return "trend_pullback", 2.0 + ret_1m
    if trend == "up" and dist_high > -0.01:
        # Pressing the 20-day high: breakout continuation.
        return "breakout_watch", 1.5 + ret_1m
    if r < 30 and trend != "down":
        # Washed out but not in a downtrend: mean-reversion bounce.
        return "oversold_bounce", 1.0 - (r - 30) / 100
    return "no_setup", ret_1m - 1.0


def screen_stocks(symbols: list[str], fetch_fn=fetch_stock_bars, min_bars: int = 60) -> list[StockScreenResult]:
    results: list[StockScreenResult] = []
    for symbol in symbols:
        try:
            df = fetch_fn(symbol, timeframe="1Day", limit=120)
        except Exception as exc:
            print(f"  skipping {symbol}: failed to fetch data ({exc})")
            continue
        if len(df) < min_bars:
            print(f"  skipping {symbol}: only {len(df)} bars, need {min_bars}")
            continue

        close = df["close"]
        sma20 = close.rolling(20).mean().iloc[-1]
        sma50 = close.rolling(50).mean().iloc[-1]
        last = float(close.iloc[-1])
        trend = "up" if last > sma20 > sma50 else "down" if last < sma20 < sma50 else "flat"
        r = rsi(close)
        dist_high = float(last / close.rolling(20).max().iloc[-1] - 1)
        setup, score = classify(close, r, dist_high, trend)

        results.append(
            StockScreenResult(
                symbol=symbol,
                close=last,
                ret_1m=float(last / close.iloc[-21] - 1),
                ret_3m=float(last / close.iloc[-63] - 1) if len(close) > 63 else 0.0,
                rsi_14=r,
                atr_pct=atr_pct(df),
                dist_from_20d_high=dist_high,
                trend=trend,
                setup=setup,
                score=score,
            )
        )

    results.sort(key=lambda x: x.score, reverse=True)
    return results


def suggest_orders(results: list[StockScreenResult], equity: float, risk_pct: float, top_n: int = 3) -> None:
    """Print policy-sized order suggestions for the top setups."""
    actionable = [r for r in results if r.setup != "no_setup"][:top_n]
    if not actionable:
        print("\nNo actionable setups today — not trading is a position too.")
        return
    print(f"\nSuggested orders (equity=${equity:.2f}, risk/trade={risk_pct:.0%}, stop=1.5x ATR, target=2x stop):")
    for r in actionable:
        stop_pct = max(0.03, 1.5 * r.atr_pct)  # never tighter than 3% on dailies
        shares = round((equity * risk_pct) / (r.close * stop_pct), 4)
        shares = min(shares, round(equity / r.close, 4))  # notional <= equity
        stop = r.close * (1 - stop_pct)
        target = r.close * (1 + 2 * stop_pct)
        print(
            f"  {r.symbol:6s} [{r.setup}] buy {shares} @ ~{r.close:.2f}, "
            f"stop {stop:.2f} (-{stop_pct:.1%}), target {target:.2f} (+{2 * stop_pct:.1%})"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Screen stocks for swing-trade setups (data via Alpaca)")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_UNIVERSE)
    parser.add_argument("--equity", type=float, default=100.0)
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.10)
    parser.add_argument("--top-n", type=int, default=3)
    args = parser.parse_args()

    results = screen_stocks(args.symbols)
    if not results:
        print("No data for any symbol — check ALPACA_API_KEY/ALPACA_API_SECRET and network access.")
        return

    rows = pd.DataFrame([r.__dict__ for r in results])
    with pd.option_context("display.float_format", "{:.3f}".format):
        print(rows.to_string(index=False))

    suggest_orders(results, args.equity, args.risk_per_trade_pct, args.top_n)


if __name__ == "__main__":
    main()
