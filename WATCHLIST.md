# Alert-Only Watchlist

Levels sourced from @KayCapitals (Instagram, posted 2026-07-08, hourly
charts). **Alert only — no automatic trading.** When a level triggers, push
an alert; entries require a fresh owner decision.

These are intraday levels and go stale fast: treat this list as EXPIRED
after **2026-07-15** unless the owner refreshes it.

| Symbol | Ref price (7/8) | Upside trigger | Upside targets | Downside trigger | Downside levels |
|--------|-----------------|----------------|----------------|------------------|-----------------|
| AVGO   | ~387.6          | >= 395.00      | 398.8, 400.7   | <= 383.30        | 378.1, 373.8    |
| TSLA   | ~393.4          | >= 396.10      | 399.9, 402.9   | <= 390.50        | 387.8, 384.6    |
| QQQ    | ~710.3          | >= 712.30      | 716.3, 718.7   | <= 705.25        | 702.3, 698.2    |
| SPY    | ~744.4          | >= 747.10      | 749.4, 751.0   | <= 739.30        | 736.4, 733.9    |

## Alert rules

- Fire ONE alert per symbol per direction (track fired alerts in the state
  file; do not re-alert every check on the same crossed level).
- Alert content: symbol, which level crossed, current price, and the
  follow-on targets from the table.
- A symbol that has fired both directions needs no further monitoring.
- After 2026-07-15, alert the owner once that the watchlist expired, then
  stop checking it.

## Context / caution

AVGO's move was news-driven (Apple contract). Levels from social posts are
one trader's opinion drawn on a chart — useful as reference points, not
signals with a track record. QQQ/SPY levels are broad-market context; a
break there says more about market direction than about a specific trade.
