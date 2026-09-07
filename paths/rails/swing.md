# SWING path — scope rails (HARD limits)

> Inlined into every `swing`-path worker's task body. Safety boundary for
> paper execution of swing/perp setups. Pulled from model-trader
> `docs/designing-gates.md`, `paper_trader/filters.py`, and `architecture.md`.

## Acceptable work

- Paper-execute a setup whose scanner status is **TAKE**, with `entry`,
  `stop`, `target`, and `direction` all set. Use the sibling **model-trader**
  package: `PaperTrader.open_trade`, `is_duplicate_setup`,
  `is_invalidated_level`. Persist to `trades.json` in the workspace.
- Compose detectors as **pass/fail gates** (not a confluence score):
  DATA_OK → HTF_BIAS → LTF_FVG → CISD_CONFIRM → LEVELS. Available detectors:
  FVG, swings, failure swings, CISD/breaker, SMT, displacement.
- Size at a fixed % of paper equity (default 1%) with the paper trader's
  leverage cap. Stops are invalidation-based ("thesis is dead"), not arbitrary
  pip counts. Default target ≥ 1R.
- Call `PaperTrader.check_exits()` against 1m candles when reporting.

## Never acceptable

- **Live / real-money orders** on Hyperliquid or anywhere else. model-trader
  is a paper trader. Do not import a live SDK to "just fill."
- A `TAKE` with any of `entry` / `stop` / `target` / `direction` unset
  (this crashes the paper trader — the final gate owns all four).
- Scoring instead of gating ("+1 HTF, +1 SMT, +1 displacement").
- Combining independent conditions into one opaque gate (the journal `reason`
  must say which gate failed).
- Duplicate setups (same entry/stop/target recently) or re-entry at a recently
  blown level until price has structurally moved away
  (`is_invalidated_level`).
- Adding daily-loss / max-drawdown "exceptions" that silently continue
  trading after a halt condition the human asked for.
- Auto-approving at the Hermes gate. The agent layer in model-trader is
  veto-only and fail-open; **this** pipeline's human gate is not optional.

## If a proposal doesn't fit

Shelve, or re-route to `watch` if the missing piece is a named WAIT trigger.
**Do not widen the rails.**
