# 11 — V1 roadmap
## Implemented
- read-only Tradier market/account adapter and reconnecting stream
- credit vertical + iron-condor construction, liquidity/delta/DTE/width/credit gates
- natural-price economics, account-aware sizing, stable candidate IDs + JSON sidecars
- exact-leg post-approval revalidation and no-chase credit rule
- options-specific SQLite paper ledger and lifecycle metrics
- conservative close pricing, 50% winner and 21-DTE management logic
- shared SQLite market state and sanitized broker+paper portfolio snapshot
- durable agent/architecture instructions and deterministic tests

## Next integration
- run against real local Tradier credentials
- wire Hermes board post-gate commands end-to-end
- add structured position-management Telegram reviews
- choose/test hard portfolio concentration limits after observing paper data
- collect at least 50 clean paper occurrences before parameter tuning

## Later data enrichment
Historical IV/IVR, OPRA trades+NBBO, raw flow features, realized vol, event feeds, cohort backtests.

## Live execution phase
Not started. Requires separate trade-scope adapter, mandatory broker preview, limit-order state machine,
reconciliation/idempotency, stale-data/daily/portfolio kill switches, restart recovery, and initial human gate.
