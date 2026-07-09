# Active Trade Plan — HOOD dip entry

Status: **ARMED** (no position yet). Owner approved 2026-07-09.
Account: Robinhood "Agentic" cash account ••••5270 (~$100 buying power).
Governed by ROBINHOOD_POLICY.md — its halts and floors override this plan.

## Thesis

HOOD is the strongest uptrend on the 2026-07-09 scan (+33% in a month,
price > 20d SMA > 50d SMA) but extended (RSI ~64, ~11% above the 20-day
average). Chasing here buys a blow-off top; the plan is to buy the first
orderly pullback while the trend is intact.

Reference marks at plan creation: last $112.90, 20d SMA ~$105,
20d high ~$117.50, ATR ~6%.

## Rules (checked on each market-hours check-in)

1. **Entry**: if HOOD last <= $106.00 -> buy ~$99 notional as a fractional
   day limit order slightly above the ask. One entry only.
2. **After entry**:
   - Stop: last <= entry x 0.91 (-9%) -> sell entire position immediately.
   - Target: last >= entry x 1.18 (+18%) -> sell entire position.
   - Both are agent-enforced on each check-in (Robinhood fractional
     positions can't carry resting GTC stops).
3. **Regroup (no entry)**: if HOOD last >= $118.00 before any dip fills,
   the dip thesis is stale -> notify owner, propose alternatives
   (V near $340 was runner-up), and disarm this plan.
4. **Time stop**: if neither trigger hits within 15 trading days
   (by 2026-07-30), notify owner and disarm.
5. **Connector down**: if the robinhood-trading MCP is unauthenticated at
   check-in, skip silently; after 3+ consecutive failed checks, notify the
   owner once to re-authenticate.

## Notify the owner when

- The entry fills (include fill price, stop, and target levels).
- Stop or target executes.
- The regroup or time-stop trigger fires.
- Never for routine no-action checks.
