# Trading Bot

An agent for researching, backtesting, and (eventually) executing trading
strategies on crypto and futures markets, with TradingView integration and a
daily trading journal.

## Roadmap

1. **Backtesting + strategy research (this milestone)** — vectorized backtest
   engine, a library of well-known strategies, performance metrics, and a
   journal that logs every backtest/trade.
2. **TradingView integration** — Pine Script translations of validated
   strategies for native TradingView backtesting, plus a webhook receiver so
   TradingView alerts can trigger live orders.
3. **Live execution** — crypto via `ccxt` (Binance/Bybit), traditional futures
   via a broker API (e.g. Interactive Brokers). Paper trading first.
4. **Optimization** — parameter sweeps / walk-forward analysis to maximize
   gains while capping drawdown.

## Layout

```
trading_bot/
  data/         OHLCV fetching (ccxt) and CSV loading
  strategies/   Strategy implementations (trend, mean-reversion, breakout)
  backtest/     Backtest engine + performance metrics
  journal/      Daily trading journal (SQLite-backed)
  pinescript/   Pine Script templates generated from strategy params
  execution/    Broker adapters (paper trading now, live later)
  cli.py        Command-line entrypoint
```

## Usage

```bash
pip install -r requirements.txt

# Fetch historical data
python -m trading_bot.cli fetch --symbol BTC/USDT --timeframe 1h --limit 1000 --out data/btc_1h.csv

# Run a backtest and log it to the journal
python -m trading_bot.cli backtest --data data/btc_1h.csv --strategy trend_following

# Show today's journal entry
python -m trading_bot.cli journal --show
```

## Strategies implemented

- **Trend following** — EMA crossover with trend filter (most widely used by
  systematic trend funds).
- **Mean reversion** — Bollinger Band + RSI reversion.
- **Breakout** — Donchian channel breakout (classic "turtle trading" style).

Each strategy exposes its parameters so the same logic can be backtested in
Python and exported to Pine Script (`trading_bot/pinescript/generator.py`) for
TradingView.

## Risk management

The backtest engine enforces position sizing, a per-trade stop loss, and a
max-drawdown circuit breaker, since the goal is maximizing gains while
minimizing large losses, not just raw return.
