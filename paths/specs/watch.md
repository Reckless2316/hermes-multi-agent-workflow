# Deliverable spec — WATCH path

## What the path produces

All files in `work/watchlist/<slug>/`:

1. `watch.json` — `{symbol, direction, missing_event, invalidation, promote_to,
   armed_at, status: "WAIT"}`. `missing_event` is one concrete sentence.
2. `report.md` — one screen of Telegram: what we're waiting for, what kills
   the idea, which path it becomes if the event prints.

## Quality bar

- `missing_event` is observable on the next scan (a candle event, a touch of
  a named FVG, a CISD through a named swing). Not a feeling.
- No `trades.json` fill on this path.
