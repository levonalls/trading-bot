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
  backtest/     Backtest engine, metrics, grid search, walk-forward optimization
  journal/      Daily trading journal (SQLite-backed)
  pinescript/   Pine Script templates generated from strategy params
  execution/    Broker adapters (ccxt for crypto, IB for futures) + risk guard
  webhook_server.py  FastAPI receiver for TradingView alerts -> broker orders
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

# Grid-search a strategy's parameters on a dataset
python -m trading_bot.cli optimize --data data/btc_1h.csv --strategy trend_following --top 10

# Walk-forward optimize: fit on rolling train windows, validate out-of-sample
python -m trading_bot.cli walk-forward --data data/btc_1h.csv --strategy trend_following \
  --train-bars 1000 --test-bars 200

# Generate a Pine Script for TradingView
python -m trading_bot.cli pinescript --strategy trend_following --symbol BTCUSDT --out trend_following.pine
```

### Optimization & walk-forward

`optimize` runs a grid search over each strategy's default parameter space
(`trading_bot/backtest/param_grids.py`) and ranks combinations by a score that
rewards return/Sharpe and penalizes drawdown — not just raw return — so the
winner isn't just the riskiest parameter set. `walk-forward` is the
overfitting check: it repeatedly fits params on a training window and scores
them on the *next*, unseen window, then reports the aggregated out-of-sample
performance. Only trust a strategy whose walk-forward summary looks good —
an in-sample-only `optimize` result is not evidence the strategy works going
forward.

### Screening: which symbols should I even trade?

```bash
python -m trading_bot.screen --exchange coinbase --quote USD --num-candidates 10 --top-n 3
```

Pulls the most liquid `quote`-denominated markets on `exchange` by 24h
volume (excluding stablecoin pairs), runs a walk-forward optimization of
every strategy against every candidate, scores each by out-of-sample
compounded return penalized for drawdown, and prints/logs the top 3
symbol+strategy combinations. Treat this as a starting shortlist, not a
final answer — rerun `walk-forward` with the full parameter grid
(`trading_bot.cli walk-forward`) on whatever it surfaces before trading it.

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
minimizing large losses, not just raw return. The live webhook server has its
own independent guardrails (see below) — backtest risk controls do not
automatically apply to live orders.

## Going live: step by step

**Do this only after a strategy has a solid out-of-sample `walk-forward`
result. Start in paper mode and stay there until you've watched it run for
real money you'd be fine losing.**

### 1. Get exchange/broker credentials

- **Crypto (ccxt)**: create API keys on your exchange (e.g. Binance). For
  paper trading, ccxt routes to the exchange's testnet automatically — you
  still need API keys, but they can be testnet keys
  (e.g. Binance Spot Testnet at testnet.binance.vision).
- **Futures (Interactive Brokers)**: install and run **Trader Workstation
  (TWS)** or **IB Gateway**, log in to a **paper trading account** first, and
  enable API access in TWS settings (Configure → API → Settings → Enable
  ActiveX and Socket Clients). Note the port (default `7497` for TWS paper).

### 2. Set environment variables

```bash
export CRYPTO_EXCHANGE=coinbase                  # any ccxt exchange id: binance, coinbase, bybit, ...
export COINBASE_API_KEY=...
export COINBASE_API_SECRET=...

export WEBHOOK_SECRET=$(openssl rand -hex 32)   # required for the webhook to accept requests
export TRADING_MODE=paper                       # "paper" or "live" — start with paper
export MAX_ORDER_SIZE=0.01                       # hard cap on size per order, in base units
export MAX_DAILY_ORDERS=20                       # hard cap on orders per day
```

The webhook server reads `{EXCHANGE}_API_KEY` / `{EXCHANGE}_API_SECRET` for
whichever exchange `CRYPTO_EXCHANGE` names (uppercased), so switching
exchanges is just changing `CRYPTO_EXCHANGE` and setting the matching key
pair — no code changes needed. Note that Coinbase's Advanced Trade API has
no sandbox: in paper mode, `CcxtBroker` automatically falls back to a local
dry run (real Coinbase price, simulated fill, nothing submitted) rather than
a sandbox order, since there's no testnet to send it to.

`TRADING_MODE=live` alone is not enough to place real orders: `CcxtBroker`
and `IBBroker` both additionally require
`TRADING_BOT_LIVE_CONFIRM=I_UNDERSTAND_LIVE_TRADING` to be set. This is
intentional — it should never be possible to go live by accident from a
stale env var.

### 3. Run the bot

There are two ways to drive trades, pick one:

**Option A — self-contained live runner.** The bot fetches live OHLCV data,
runs the strategy itself, and places orders on signal changes. No
TradingView required:

```bash
pip install -r requirements.txt
python -m trading_bot.live_runner --strategy trend_following --symbol BTC/USD --timeframe 1h --poll-seconds 300
```

It polls every `--poll-seconds`, persists its last known position to
`live_runner_state_<strategy>_<symbol>.json` (so a restart doesn't re-fire an
already-placed order), and sizes each order so a stop-loss hit risks
`--risk-per-trade-pct` (default 1%) of your available balance — capped so
the trade's total notional value never exceeds `--max-position-pct`
(default 20%) of your balance, regardless of stop distance. To halt it
immediately — including across process restarts — create the file
`live_runner.kill` in its working directory; it's checked before every poll
and the runner exits as soon as it sees it. Delete the file to resume.

**Option B — TradingView-driven webhook.** TradingView's Pine Script runs
the strategy and decides entries/exits; this bot just executes the alerts
it receives:

```bash
uvicorn trading_bot.webhook_server:app --host 0.0.0.0 --port 8000
```

**Trading multiple coins at once:** use `--pairs` instead of `--strategy`/`--symbol`
to run several `strategy:symbol` combos in one process, sharing a single
risk-aware equity budget:

```bash
python -m trading_bot.live_runner --pairs mean_reversion:ADA/USD mean_reversion:SOL/USD \
  --timeframe 1h --poll-seconds 300 --risk-per-trade-pct 0.01 --max-portfolio-pct 0.20
```

`--max-portfolio-pct` caps the *combined* notional across all pairs (here, 20%
of equity total, not 20% each) — adding more symbols narrows each one's share
of that budget rather than silently multiplying total exposure. Each pair
still gets its own state file, so you can freely add/remove symbols across
restarts.

For TradingView's servers to reach it, the server needs a public HTTPS URL
— either deploy it (a small VM/cloud box) or tunnel it during testing
(e.g. `ngrok http 8000`). Never expose it without `WEBHOOK_SECRET` set.

### 4. Wire up TradingView (only if using Option B)

1. Open a Pine Script generated by `trading_bot.cli pinescript` in
   TradingView's Pine Editor, and add it to your chart.
2. Confirm its backtest behavior in TradingView's Strategy Tester matches
   what you saw in the Python backtest (same params, similar trade pattern —
   it won't be identical due to differences in execution modeling).
3. Create an **Alert** on the `alertcondition()`s defined in the script
   (e.g. "Trend Long" / "Trend Short"). Each alert template already includes
   a JSON payload like `{"action": "long", "symbol": "BTCUSDT"}` — add
   `"market": "crypto"` (or `"futures"`) and `"size": ...` to that JSON if
   you want to override the defaults.
4. In the alert's **Webhook URL** field, enter
   `https://<your-server>/webhook`. In **Notifications**, enable Webhook.
5. TradingView's alert webhooks don't support custom headers, so when you
   can't set `x-webhook-secret`, embed the secret in the JSON payload
   instead (e.g. `{"action": "long", "symbol": "BTCUSDT", "secret": "..."}`)
   and adjust `_check_auth` in `webhook_server.py` to read it from the body.

### 5. Verify in paper mode first

Watch orders land in your exchange's testnet account / IB paper account and
check the journal:

```bash
python -m trading_bot.cli journal --show
```

### 6. Flip to live (only when ready)

```bash
export TRADING_MODE=live
export TRADING_BOT_LIVE_CONFIRM=I_UNDERSTAND_LIVE_TRADING
# restart the webhook server so it picks up the new env vars
```

### Kill switch

If anything looks wrong, halt all trading immediately without restarting
the server:

```bash
curl -X POST https://<your-server>/kill -H "x-webhook-secret: $WEBHOOK_SECRET"
# investigate, then re-enable:
curl -X POST https://<your-server>/rearm -H "x-webhook-secret: $WEBHOOK_SECRET"
```

The kill switch, the `MAX_ORDER_SIZE` cap, and the `MAX_DAILY_ORDERS` cap
(`trading_bot/execution/risk.py`) are independent of whatever risk logic is
in the strategy itself — they exist specifically to bound the damage a bad
alert, a bug, or a runaway loop can do.
