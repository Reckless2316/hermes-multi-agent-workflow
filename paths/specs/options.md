# Deliverable spec — OPTIONS path

> Inlined into options-path workers. Pins the artifact so fulfillment is a
> paper trade + journal, not a prose essay.

## What the path produces

All files in the persistent workspace `work/options/<slug>/`:

1. `setup.json` — `ScanResult.to_dict()` from `desk` (status TAKE, legs, credit,
   max_loss, capital_efficiency, profit_target, management_dte). Do not invent
   a different structure.
2. `trades.json` — `desk.paper.PaperTrader` journal after `paper_execute`.
3. `report.md` — fill recap for Telegram.

## Quality bar

- Max loss is a number in account currency, copied from the scanner.
- Every leg is specified. No "around the 500c."
- `python -m desk.paper` is not a live broker. No Tradier order endpoints.
- Duplicate / BP filters already ran in `desk/`; do not resize.
