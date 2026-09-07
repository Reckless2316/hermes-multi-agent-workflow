# Deliverable spec — SWING path

> Inlined into swing-path workers. Output matches model-trader's live loop:
> scan → filter → paper execute → journal.

## What the path produces

All files in `work/swings/<slug>/`:

1. `setup.json` — `SetupResult.to_dict()` with `status: TAKE`, `gates_passed`
   listed in order, `reason: "All gates passed"` (or the specific WAIT that
   was upgraded — if it was not upgraded, this is the wrong path).
2. `trades.json` — `PaperTrader` journal entry for this fill.
3. `report.md` — fill recap: symbol, direction, entry/stop/target, size, R,
   filters checked (duplicate? invalidated level?), metrics snapshot from
   `model_trader.paper_trader.metrics.calculate_metrics` if a desk journal
   exists.

## Quality bar

- Gate names match model-trader style (`HTF_BIAS`, `LTF_FVG`, `CISD_CONFIRM`).
- Stop is an invalidation price, target is at least 1R unless the proposal
  (and the human's `modify`) said otherwise.
- Import detectors from `model_trader.detectors` when you re-verify; do not
  reimplement FVG/CISD by eye in the fulfill step.
- No live exchange orders.
