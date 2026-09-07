# WATCH path — scope rails (HARD limits)

> Inlined into every `watch`-path worker. WAIT setups from model-trader
> (`SetupStatus.WAIT`) are armed as monitors — they are **not** trades.

## Acceptable work

- Write a watchlist record: symbol, direction, the **one named event** still
  missing (e.g. "CISD candle through swing low on 5m"), invalidation, and
  what happens if the event prints (promote to options or swing TAKE).
- Arm a check the next scout cycle can see (workspace `watchlist.json`).
  Do not spam Telegram on every scan.

## Never acceptable

- Opening a paper (or live) position because "it's close enough."
- WAIT with a vague trigger ("more confirmation," "see how it looks").
  If you cannot name the event, this item should have been `skip` / shelved.
- Turning a watch into a market order in the same fulfillment chain.

## If a proposal doesn't fit

Shelve. Do not invent a trigger to keep the item alive.
