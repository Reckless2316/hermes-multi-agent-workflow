# Example: automated-trading (the live desk)

Root `triage.yaml` is this pipeline. Deep map: **`docs/08-trading-domain.md`**.
Filled-in scout skills live in `skills/templates/triage-scout-options/` and
`triage-scout-swing/`.

## What it does

- **Scouts** (`options_scout` twice an hour in US cash hours; `swing_scout`
  hourly 24/7) watch defined-risk options flow and swing structure (model-trader
  gates: HTF bias → LTF FVG → CISD → levels).
- **Rubric** scores setup clarity / risk-reward / gate completeness / market
  context / uniqueness; threshold 70/100.
- **Research** verifies the setup, gathers HTF/IV/news context, and runs a
  **risk audit** (duplicate + invalidated-level filters, sizing) that emits
  `disposition`.
- **Route:** `options_take` → paper options; `swing_take` → paper swing/perp;
  `wait` → arm a monitor; `skip` / `no_edge` → **shelve**.
- **Gate:** one Telegram approval per TAKE/WAIT. Never auto-approve.
- **Fulfill:** paper journal (`trades.json` / `watch.json`) + `report.md`.
  Live money is forbidden by the scope rails.

## Stand it up

```bash
python -m cli.triage validate
python -m cli.triage scaffold
hermes kanban boards create trading
```

Then `docs/07-runbook.md` (kanban toolset on both scout profiles, crons in the
**gateway** store, smoke-test one sweep before resuming cron).
