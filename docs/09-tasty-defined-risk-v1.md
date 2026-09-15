# 09 — TASTY_DEFINED_RISK_V1
V1 prioritizes defined risk and capital efficiency over maximizing headline POP. It supports short put
verticals, short call verticals, and iron condors. Defaults are configurable hypotheses: 25–50 DTE
(target 45), short delta target .30/range .20–.35, 30% minimum credit/width, widths 2.5–20,
50% winner target, 21-DTE management, 1% equity max-loss budget per new position.

Entry economics are conservative natural credit: `short bid - long ask`; close economics buy original
shorts at ask and sell hedges at bid. For a vertical, max loss = `(width-credit)*100`.
Capital efficiency = target-profit dollars / BPR proxy. Midpoint is only a reference mark.
Tradier provides current IV/Greeks but not historical IV Rank; IVR remains explicitly unavailable until
real history is connected. No LLM may substitute for it.


## Market-hours freshness
Scans, post-approval paper fills, and automatic paper closes require Tradier market clock state `open`. Closed/unknown states do not consume stale chains as executable evidence.
