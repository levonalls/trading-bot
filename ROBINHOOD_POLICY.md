# Robinhood Agentic Account — Trading Policy

Applies to the Robinhood "Agentic" cash account (••••5270), traded via the
`robinhood-trading` MCP server. Agreed 2026-07-08 with account owner.

## Account profile

- Starting equity: ~$100 cash (explicitly designated risk capital)
- Cash account: no PDT rule, but T+1 settlement — do not buy with unsettled
  funds and sell same day (good-faith violation risk). Practical ceiling:
  one full account turnover per day.
- Equities only. No options (no option level on this account), no margin,
  no crypto (not exposed through the agent interface).

## Risk parameters (deliberately loosened for the first $100)

The owner chose an aggressive profile for this starter balance. Sizes are
loose; structure is not.

| Parameter | Value |
|---|---|
| Max risk per trade | 10% of equity (~$10) |
| Max position size | 100% of equity, one open position at a time |
| Stop loss | Mandatory on every trade, 5–8% below entry (agent-enforced) |
| Minimum reward:risk | 2:1 (target at least twice the stop distance) |
| Daily loss halt | −20% in a day → no more trades until next session |
| Account floor | Equity ≤ $50 → halt all trading, review with owner before resuming |
| Max orders per day | 5 |
| Order types | Limit orders preferred; fractional orders are day-only |

## Non-negotiables (do not loosen further without explicit owner sign-off)

1. Never trade without a defined stop and target set before entry.
2. Never average down into a losing position.
3. The $50 floor and daily −20% halt override any open trade thesis.
4. If these parameters are scaled to a larger balance later, revert to the
   conservative profile (1% risk/trade, 20% max position) unless the owner
   re-confirms otherwise — the loose profile is for the first $100 only.
