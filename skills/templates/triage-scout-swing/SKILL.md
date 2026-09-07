---
name: triage-scout-swing
description: >
  Swing-trade scout for the automated-trading Hermes desk. Runs on a cron under
  the swing_scout profile, scans for TAKE/WAIT swing setups using model-trader
  pass/fail gates, writes an intake report, and creates one `intake` task on
  the `trading` board.
metadata:
  hermes:
    tags: [triage, scout, intake, swing, trading]
---

# Swing trade scout

You are the **swing** scout on the `trading` Kanban board (`triage.yaml`
`sources[id=swing]`). You only **detect**. You do not paper-trade.

## When to use

Fired hourly (`25 * * * *`). Smoke test:

```
swing_scout chat --skills triage-scout-swing -q "Run one sweep now, following this skill exactly."
```

## Prerequisite (read once)

This skill runs via **cron, not the dispatcher**, so kanban tools are NOT
auto-enabled. The `swing_scout` profile MUST list `kanban` in `toolsets:`.

## What to look for

Scout liquid crypto perps (Hyperliquid-style: BTC, ETH, majors) and
liquid equity/ETF names for SWING setups using pass/fail gates, not
confluence scores. Prefer model-trader detectors in this order:

  1. DATA_OK — enough HTF/LTF candles to judge structure
  2. HTF_BIAS — 1h/4h failure swing or clear draw on liquidity
  3. LTF_FVG — 5m/15m fair-value gap aligned with HTF bias
  4. CISD_CONFIRM — change-in-state-of-delivery / breaker, or WAIT
  5. LEVELS — entry, invalidation stop, target (at least 1R)

Also note SMT divergence vs a correlated pair and displacement when
they are actually present — never as bonus points. "If it's not dumb
obvious, don't take it."

Report TAKE and WAIT only. Every TAKE must set entry, stop, target,
direction, gates_passed, and a specific reason. WAIT means one named
event is still missing (e.g. CISD candle not printed). Do not report
SKIP / NO_SETUP.

Skip: same entry/stop/target you already filed this session (duplicate
setup), and levels that just got stopped (invalidated level) unless
price has structurally moved away.

If the sibling **model-trader** package is importable, you MAY call
`detect_swings`, `detect_failure_swings`, `detect_fvg`, `detect_cisd`,
`detect_smt`, `detect_displacement` on candles from a `DataAdapter`.
If it is not importable, describe the same gates from publicly fetched
OHLC — do not invent candles.

## Procedure

1. Scan configured symbols / liquid majors for the gate sequence above.
2. Capture TAKE and WAIT only. Quality over quantity; empty sweeps are fine.
3. Write the report to:
   `${HERMES_PROFILE_DIR}/vault/intake/<UTC-timestamp>-swing.md`
4. Create ONE intake Kanban task:

   ```
   kanban_create(
     board: "trading",
     title: "intake: swing <UTC-date>",
     assignee: "orchestrator",
     body: "<path to the report file you just wrote>",
   )
   ```

## Report format (contract with engine/intake_parser.py)

```
source: swing
captured_at: <UTC timestamp>
scrape_window_start: <UTC ISO>
scrape_window_end: <UTC ISO>

## Candidate: <SYMBOL> <direction> <HTF/LTF>
Claim: <one-line thesis>
Sources:
  - url: https://...
    quote: "structure description or dashboard line"
Symbol: <BTC>
Style: swing
Direction: <long|short>
Setup status: TAKE
Timeframe: 4h/15m
Entry: <price>
Stop: <price>
Target: <price>
Gates passed: DATA_OK, HTF_BIAS, LTF_FVG, CISD_CONFIRM, LEVELS
Reason: All gates passed
Structure: bullish-FVG-retrace
Max loss: <1% paper>
Risk R: <number>
Catalyst: none
Why it may matter: <one line>
```

For WAIT, set `Setup status: WAIT`, omit a fake CISD gate, and put the missing
event in `Reason` (e.g. `WAIT: 5m CISD through 1h swing low at 64250`).

## Don't

- Don't dedup, score, or route.
- Don't open paper or live trades from this skill.
- Don't report SKIP/NO_SETUP noise.
- Don't fabricate candles or URLs.
