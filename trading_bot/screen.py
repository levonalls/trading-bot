from __future__ import annotations

import argparse
from dataclasses import dataclass

import pandas as pd

from trading_bot.backtest.param_grids import make_factory
from trading_bot.backtest.walk_forward import summarize_windows, walk_forward_optimize
from trading_bot.data.fetch import fetch_ohlcv
from trading_bot.journal.journal import Journal, JournalEntry

# Smaller grids than the full DEFAULT_GRIDS so screening many symbols x
# strategies finishes in a reasonable time; optimize/walk-forward on a
# shortlisted symbol later with the full grid for the final parameter choice.
# The intraday day-trading strategies are deliberately absent: this screen
# runs on 24/7 crypto markets, where session-based logic (opening range,
# session VWAP, overnight gaps) doesn't apply.
SCREEN_GRIDS = {
    "trend_following": {"fast_ema": [10, 20], "slow_ema": [40, 50], "trend_ema": [200],
                          "stop_loss_pct": [0.02], "take_profit_pct": [0.06]},
    "mean_reversion": {"bb_window": [20], "bb_std": [2.0], "rsi_window": [14],
                         "stop_loss_pct": [0.02], "take_profit_pct": [0.04]},
    "breakout": {"entry_window": [20], "exit_window": [10],
                  "stop_loss_pct": [0.02], "take_profit_pct": [0.06]},
}


@dataclass
class ScreenResult:
    symbol: str
    strategy: str
    summary: dict
    score: float


def score_summary(summary: dict) -> float:
    if not summary:
        return float("-inf")
    return summary["compounded_oos_return"] - 2 * abs(summary["worst_oos_drawdown"])


def top_coinbase_symbols(exchange_id: str, quote: str, limit: int) -> list[str]:
    """Rank Coinbase markets by 24h quote volume and return the most liquid
    pairs against `quote` (excluding the quote currency itself and other
    stablecoins, which aren't worth "trading" against each other).
    """
    import ccxt

    client = getattr(ccxt, exchange_id)()
    tickers = client.fetch_tickers()
    stablecoins = {"USD", "USDC", "USDT", "DAI", "GUSD", "PAX", "PYUSD"}

    candidates = []
    for symbol, ticker in tickers.items():
        if "/" not in symbol:
            continue
        base, _, q = symbol.partition("/")
        if q != quote or base in stablecoins:
            continue
        volume = ticker.get("quoteVolume") or 0
        candidates.append((symbol, volume))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return [symbol for symbol, _ in candidates[:limit]]


def screen(
    exchange_id: str = "coinbase",
    quote: str = "USD",
    num_candidates: int = 10,
    top_n: int = 3,
    timeframe: str = "1h",
    bars: int = 1000,
    train_bars: int = 600,
    test_bars: int = 150,
) -> list[ScreenResult]:
    symbols = top_coinbase_symbols(exchange_id, quote, num_candidates)
    print(f"Screening {len(symbols)} {quote}-quoted symbols on {exchange_id}: {symbols}")

    results: list[ScreenResult] = []
    for symbol in symbols:
        try:
            df = fetch_ohlcv(symbol, timeframe=timeframe, limit=bars, exchange=exchange_id)
        except Exception as exc:
            print(f"  skipping {symbol}: failed to fetch data ({exc})")
            continue
        if len(df) < train_bars + test_bars:
            print(f"  skipping {symbol}: only {len(df)} bars, need {train_bars + test_bars}")
            continue

        for strategy_name, grid in SCREEN_GRIDS.items():
            factory = make_factory(strategy_name)
            windows = walk_forward_optimize(df, factory, grid, train_bars=train_bars, test_bars=test_bars)
            summary = summarize_windows(windows)
            score = score_summary(summary)
            print(f"  {symbol} / {strategy_name}: score={score:.4f} summary={summary}")
            results.append(ScreenResult(symbol, strategy_name, summary, score))

    results.sort(key=lambda r: r.score, reverse=True)

    seen_symbols: set[str] = set()
    top: list[ScreenResult] = []
    for r in results:
        if r.symbol in seen_symbols:
            continue
        seen_symbols.add(r.symbol)
        top.append(r)
        if len(top) == top_n:
            break

    journal = Journal()
    for r in top:
        journal.log(JournalEntry(
            entry_date=pd.Timestamp.today().date().isoformat(),
            strategy=r.strategy,
            symbol=r.symbol,
            metrics=r.summary,
            notes=f"screen: ranked top-{top_n} candidate, score={r.score:.4f}",
        ))

    return top


def main() -> None:
    parser = argparse.ArgumentParser(description="Screen Coinbase markets and rank strategy/symbol combos")
    parser.add_argument("--exchange", default="coinbase")
    parser.add_argument("--quote", default="USD")
    parser.add_argument("--num-candidates", type=int, default=10)
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--bars", type=int, default=1000)
    parser.add_argument("--train-bars", type=int, default=600)
    parser.add_argument("--test-bars", type=int, default=150)
    args = parser.parse_args()

    top = screen(
        exchange_id=args.exchange,
        quote=args.quote,
        num_candidates=args.num_candidates,
        top_n=args.top_n,
        timeframe=args.timeframe,
        bars=args.bars,
        train_bars=args.train_bars,
        test_bars=args.test_bars,
    )

    print(f"\nTop {len(top)} symbol/strategy combos (out-of-sample):")
    for r in top:
        print(f"  {r.symbol} -> {r.strategy} (score={r.score:.4f}): {r.summary}")


if __name__ == "__main__":
    main()
