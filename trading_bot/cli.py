from __future__ import annotations

import argparse
from datetime import date

from trading_bot.backtest.engine import BacktestEngine
from trading_bot.backtest.metrics import compute_metrics
from trading_bot.backtest.optimize import grid_search
from trading_bot.backtest.param_grids import DEFAULT_GRIDS, make_factory
from trading_bot.backtest.walk_forward import summarize_windows, walk_forward_optimize
from trading_bot.data.fetch import fetch_ohlcv, load_csv
from trading_bot.journal.journal import Journal, JournalEntry
from trading_bot.pinescript.generator import generate_pine_script
from trading_bot.strategies.breakout import BreakoutStrategy
from trading_bot.strategies.mean_reversion import MeanReversionStrategy
from trading_bot.strategies.trend_following import TrendFollowingStrategy

STRATEGIES = {
    "trend_following": TrendFollowingStrategy,
    "mean_reversion": MeanReversionStrategy,
    "breakout": BreakoutStrategy,
}


def cmd_fetch(args: argparse.Namespace) -> None:
    df = fetch_ohlcv(args.symbol, timeframe=args.timeframe, limit=args.limit, exchange=args.exchange)
    df.to_csv(args.out)
    print(f"Wrote {len(df)} rows to {args.out}")


def cmd_backtest(args: argparse.Namespace) -> None:
    df = load_csv(args.data)
    strategy = STRATEGIES[args.strategy]()
    result = BacktestEngine().run(df, strategy)
    metrics = compute_metrics(result.equity_curve, result.trades)

    print(f"Strategy: {strategy.name}")
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    journal = Journal()
    journal.log(
        JournalEntry(
            entry_date=date.today().isoformat(),
            strategy=strategy.name,
            symbol=args.symbol,
            metrics=metrics,
            notes=args.notes or "",
        )
    )
    print("Logged to journal.")


def cmd_journal(args: argparse.Namespace) -> None:
    journal = Journal()
    print(journal.to_markdown(args.date))


def cmd_optimize(args: argparse.Namespace) -> None:
    df = load_csv(args.data)
    spec = DEFAULT_GRIDS[args.strategy]
    factory = make_factory(args.strategy)
    results = grid_search(df, factory, spec["grid"])

    print(f"Top {args.top} parameter sets for {args.strategy} (by score):\n")
    print(results.head(args.top).to_string(index=False))

    best = results.iloc[0]
    journal = Journal()
    journal.log(
        JournalEntry(
            entry_date=date.today().isoformat(),
            strategy=args.strategy,
            symbol=args.symbol,
            metrics=best.to_dict(),
            notes=f"grid_search best params: {best[list(spec['grid'].keys())].to_dict()}",
        )
    )
    print("\nLogged best result to journal.")


def cmd_walk_forward(args: argparse.Namespace) -> None:
    df = load_csv(args.data)
    spec = DEFAULT_GRIDS[args.strategy]
    factory = make_factory(args.strategy)

    windows = walk_forward_optimize(
        df,
        factory,
        spec["grid"],
        train_bars=args.train_bars,
        test_bars=args.test_bars,
        step_bars=args.step_bars,
    )
    summary = summarize_windows(windows)

    for i, w in enumerate(windows):
        print(
            f"Window {i}: train [{w.train_start} -> {w.train_end}], "
            f"test [{w.test_start} -> {w.test_end}]"
        )
        print(f"  best_params: {w.best_params}")
        print(f"  oos_metrics: {w.test_metrics}")

    print("\nOut-of-sample summary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    journal = Journal()
    journal.log(
        JournalEntry(
            entry_date=date.today().isoformat(),
            strategy=args.strategy,
            symbol=args.symbol,
            metrics=summary,
            notes=f"walk-forward over {len(windows)} windows",
        )
    )
    print("\nLogged walk-forward summary to journal.")


def cmd_pinescript(args: argparse.Namespace) -> None:
    strategy = STRATEGIES[args.strategy]()
    script = generate_pine_script(strategy, symbol=args.symbol)
    if args.out:
        with open(args.out, "w") as f:
            f.write(script)
        print(f"Wrote Pine Script to {args.out}")
    else:
        print(script)


def main() -> None:
    parser = argparse.ArgumentParser(prog="trading_bot")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="Fetch OHLCV data via ccxt")
    p_fetch.add_argument("--symbol", required=True)
    p_fetch.add_argument("--timeframe", default="1h")
    p_fetch.add_argument("--limit", type=int, default=1000)
    p_fetch.add_argument("--exchange", default="binance")
    p_fetch.add_argument("--out", required=True)
    p_fetch.set_defaults(func=cmd_fetch)

    p_backtest = sub.add_parser("backtest", help="Run a backtest and log it to the journal")
    p_backtest.add_argument("--data", required=True)
    p_backtest.add_argument("--strategy", choices=STRATEGIES.keys(), required=True)
    p_backtest.add_argument("--symbol", default="UNKNOWN")
    p_backtest.add_argument("--notes", default="")
    p_backtest.set_defaults(func=cmd_backtest)

    p_journal = sub.add_parser("journal", help="Show journal entries")
    p_journal.add_argument("--date", default=None, help="YYYY-MM-DD, defaults to today")
    p_journal.add_argument("--show", action="store_true")
    p_journal.set_defaults(func=cmd_journal)

    p_optimize = sub.add_parser("optimize", help="Grid-search strategy params on a dataset")
    p_optimize.add_argument("--data", required=True)
    p_optimize.add_argument("--strategy", choices=DEFAULT_GRIDS.keys(), required=True)
    p_optimize.add_argument("--symbol", default="UNKNOWN")
    p_optimize.add_argument("--top", type=int, default=10)
    p_optimize.set_defaults(func=cmd_optimize)

    p_wf = sub.add_parser("walk-forward", help="Walk-forward optimize and validate out-of-sample")
    p_wf.add_argument("--data", required=True)
    p_wf.add_argument("--strategy", choices=DEFAULT_GRIDS.keys(), required=True)
    p_wf.add_argument("--symbol", default="UNKNOWN")
    p_wf.add_argument("--train-bars", type=int, default=500, dest="train_bars")
    p_wf.add_argument("--test-bars", type=int, default=100, dest="test_bars")
    p_wf.add_argument("--step-bars", type=int, default=None, dest="step_bars")
    p_wf.set_defaults(func=cmd_walk_forward)

    p_pine = sub.add_parser("pinescript", help="Generate a Pine Script for TradingView")
    p_pine.add_argument("--strategy", choices=STRATEGIES.keys(), required=True)
    p_pine.add_argument("--symbol", default="BTCUSDT")
    p_pine.add_argument("--out", default=None)
    p_pine.set_defaults(func=cmd_pinescript)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
