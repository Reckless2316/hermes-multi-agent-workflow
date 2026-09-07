# Deliverable spec — OPTIONS path

> Inlined into options-path workers. Pins the artifact so fulfillment is a
> paper trade + journal, not a prose essay.

## What the path produces

All files in the persistent workspace `work/options/<slug>/`:

1. `setup.json` — model-trader `SetupResult.to_dict()` plus options extras:
   `structure`, `legs[]` (expiry, strike, right, qty, side), `debit_credit`,
   `max_loss`, `iv_rank`, `catalyst`. `status` must be `TAKE`.
2. `trades.json` — paper journal after `paper_execute` (append-only; never
   rewrite unrelated fills). Use the model-trader `Trade` fields.
3. `report.md` — skimmable fill recap for Telegram: symbol, structure, max
   loss, R, journal id, and the "am I actually taking this?" checklist
   answers (see `paths/philosophy.md`).

## Quality bar

- Max loss is a number in account currency, not "small."
- Every leg is specified. No "around the 500c."
- Duplicate and invalidated-level filters were run against this workspace's
  journal (and `work/options/trades.json` if you keep a desk-wide journal).
- No live broker calls.
