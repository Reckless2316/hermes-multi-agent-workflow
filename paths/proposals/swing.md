# SWING proposal template

> Orchestrator fills this in and sends it at the human gate. Skimmable on a
> phone. Reply verbs from `gate:` — **no leading slash**.

```
📊 SWING proposal: <title>   (slug: <slug>)

Setup
- Symbol: <symbol>   Direction: <long|short>
- Timeframes: HTF <4h/1h>  LTF <15m/5m>
- Entry: <price>   Stop (invalidation): <price>   Target: <price>   R: <n>
- Gates passed: <DATA_OK, HTF_BIAS, …>
- Reason: <one line>

Why take it
- Score: <total>/100 (<short breakdown>)
- Detectors: <FVG / failure swing / CISD / SMT / displacement — only those that fired>
- Duplicate setup filter: <clear | blocked>
- Invalidated-level filter: <clear | blocked>
- Correlation / SMT: <n/a | pair + result>

"Am I actually taking this?"
- Dumb obvious? <yes/no>
- Missing a named WAIT event? <no for TAKE>
- If any answer is off → watch or shelve, do not propose TAKE.

Paper plan
- Size: <1% of paper equity, leverage cap from model-trader>
- Executor: model_trader.paper_trader.PaperTrader
- LIVE MONEY: no

Reply:  approve <slug>   |   shelve <slug>: <reason>   |   modify <slug>: <change>
```
